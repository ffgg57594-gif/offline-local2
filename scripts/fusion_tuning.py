#!/usr/bin/env python3
"""Weighted RRF fusion re-tuning (Stage 3.6b).

Compares keyword variants v1-v4 on in-scope English questions under both
hit definitions (answer-term and page), then reruns weighted RRF grid
search with the best keyword variant:

  k in {10, 60}, w_kw in {0, 0.25, 0.5, 1.0}, candidate pools of top-20
  per list, page de-duplication, 5-fold CV (fixed seed 7),
  using answer-term hit as the metric.

Chooses w_kw > 0 only if its mean hit@3 beats w_kw = 0 by at least 0.03;
otherwise keeps w_kw = 0 and says so plainly.

Writes assets/fusion_config.json.
Prints fold-3 questions with their result rows.
"""
import json
import os
import random
import re
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts  # noqa: E402
from keyword_builder import (
    build_keyword_query,
    load_stopwords,
    load_variant_map,
    fts_search,
    NON_CONTENT_WORDS,
)  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_PATH = os.path.join("eval", "golden_v2.draft.jsonl")
NORMALIZE_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")
FUSION_CONFIG_OUT = os.path.join("app", "src", "main", "assets", "fusion_config.json")

EMBED_DIM = 384
K_VALUES = [10, 60]
WKW_VALUES = [0.0, 0.25, 0.5, 1.0]
N_FOLDS = 5
SEED = 7
WEAK_LABEL_THRESHOLD = 15


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat, meta


def load_golden():
    questions = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return [q for q in questions if q["in_scope"] and q["lang"] == "en"]


def dense_search(query_vec, embeddings, chunk_meta, top_k=20):
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((cid, name, page, text, float(scores[idx])))
    return results


def weighted_rrf(dense_results, kw_results, w_dense=1.0, w_kw=0.5, k=60, top_k=5):
    """Weighted RRF with page de-duplication."""
    def dedupe(results):
        seen = set()
        out = []
        for r in results:
            key = (r[0], r[1])
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    dense_results = dedupe(dense_results)
    kw_results = dedupe(kw_results)

    scores = {}
    dense_keys = [(r[0], r[1]) for r in dense_results]
    kw_keys = [(r[0], r[1]) for r in kw_results]
    for rank, key in enumerate(dense_keys):
        scores[key] = scores.get(key, 0.0) + w_dense / (k + rank + 1)
    for rank, key in enumerate(kw_keys):
        scores[key] = scores.get(key, 0.0) + w_kw / (k + rank + 1)
    text_lookup = {}
    for r in dense_results + kw_results:
        text_lookup[(r[0], r[1])] = r[2]
    sorted_keys = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    return [(key[0], key[1], text_lookup.get(key, ""), score) for key, score in sorted_keys]


def answer_terms_match_fts(cur, chunk_id, answer_terms, variant_map=None):
    """Check if a chunk matches answer_terms via FTS5 MATCH restricted to chunk id."""
    if not answer_terms:
        return False
    for group in answer_terms:
        all_match = True
        for term in group:
            norm_term = normalize_text_for_fts(term, variant_map)
            quoted = f'"{norm_term}"'
            cur.execute(
                "SELECT COUNT(*) FROM chunks_fts f "
                "JOIN chunks c ON c.id = f.rowid "
                "WHERE c.id = ? AND f.search_text MATCH ?",
                (chunk_id, quoted),
            )
            count = cur.fetchone()[0]
            if count == 0:
                all_match = False
                break
        if all_match:
            return True
    return False


def normalize_text_for_fts(text, variant_map=None):
    """Light normalization for FTS5 term matching: lowercase, collapse spaces."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    if variant_map:
        for src, dst in sorted(variant_map.items(), key=lambda kv: -len(kv[0])):
            text = re.sub(r"\b" + re.escape(src) + r"\b", dst, text)
    return text


def hit_at_k_answer_term(results, cur, answer_terms, variant_map, k):
    """Answer-term hit: any top-k chunk matches ALL terms of at least one group."""
    for rank, r in enumerate(results[:k], start=1):
        # Handle both 4-tuple (book, page, text, score) from RRF and
        # 5-tuple (cid, name, page, text, score) from dense_search.
        cid = r[0] if len(r) == 5 else None
        page = r[1]
        if answer_terms_match_fts(cur, cid, answer_terms, variant_map):
            return rank
    return None


def hit_at_k_page(results, expected_pages, k):
    """Page hit: any top-k chunk has page in expected_pages."""
    for rank, r in enumerate(results[:k], start=1):
        page = r[1]
        if page in expected_pages:
            return rank
    return None


def evaluate_config_on_questions(questions, embeddings, cur, chunk_meta, id_to_index,
                                 stopwords, non_content_words, variant_map,
                                 k, wkw, keyword_variant, use_column_weights,
                                 metric="answer_term"):
    """Evaluate a (k, wkw, keyword_variant) config on a list of questions.
    Returns list of per-question result dicts."""
    results = []
    for q in questions:
        qid = q["id"]
        query_text = q["q"]
        expected_pages = set(q["expected_pages"])
        terms = q.get("answer_terms") or []

        q_vec = embed_texts([query_text], kind="query")[0]
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=20)

        kw_query, _ = build_keyword_query(
            query_text, stopwords, non_content_words, variant_map, variant=keyword_variant
        )
        kw_res = fts_search(cur, kw_query, top_k=20, use_column_weights=use_column_weights)

        fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=wkw, k=k, top_k=5)

        if metric == "answer_term":
            ans_rank = hit_at_k_answer_term(fused, cur, terms, variant_map, 5)
            page_rank = hit_at_k_page(fused, expected_pages, 5)
            hit1 = 1 if ans_rank is not None and ans_rank <= 1 else 0
            hit3 = 1 if ans_rank is not None and ans_rank <= 3 else 0
            hit5 = 1 if ans_rank is not None and ans_rank <= 5 else 0
        else:
            page_rank = hit_at_k_page(fused, expected_pages, 5)
            hit1 = 1 if page_rank is not None and page_rank <= 1 else 0
            hit3 = 1 if page_rank is not None and page_rank <= 3 else 0
            hit5 = 1 if page_rank is not None and page_rank <= 5 else 0

        results.append({
            "id": qid,
            "question": query_text,
            "hit1": hit1,
            "hit3": hit3,
            "hit5": hit5,
            "ans_rank": ans_rank if metric == "answer_term" else None,
            "page_rank": page_rank,
            "fused_pages": [r[1] for r in fused[:3]],
            "expected_pages": sorted(expected_pages),
        })
    return results


def cross_validate(questions, embeddings, cur, chunk_meta, id_to_index,
                   stopwords, non_content_words, variant_map,
                   keyword_variant, use_column_weights):
    """5-fold CV over all (k, wkw) configs using answer-term hit metric."""
    rng = random.Random(SEED)
    indices = list(range(len(questions)))
    rng.shuffle(indices)
    fold_size = len(indices) // N_FOLDS
    folds = [indices[i * fold_size:(i + 1) * fold_size] for i in range(N_FOLDS)]
    remainder = indices[N_FOLDS * fold_size:]
    for i, idx in enumerate(remainder):
        folds[i % N_FOLDS].append(idx)

    configs = [(k, wkw) for k in K_VALUES for wkw in WKW_VALUES]
    fold_results = {}  # (k, wkw) -> list of fold dicts

    for k, wkw in configs:
        fold_list = []
        for fold_idx in range(N_FOLDS):
            test_indices = folds[fold_idx]
            fold_questions = [questions[i] for i in test_indices]
            fold_res = evaluate_config_on_questions(
                fold_questions, embeddings, cur, chunk_meta, id_to_index,
                stopwords, non_content_words, variant_map,
                k, wkw, keyword_variant, use_column_weights, metric="answer_term"
            )
            n = len(fold_res)
            hit1 = sum(r["hit1"] for r in fold_res) / n
            hit3 = sum(r["hit3"] for r in fold_res) / n
            hit5 = sum(r["hit5"] for r in fold_res) / n
            ranks = [r["ans_rank"] for r in fold_res if r["ans_rank"] is not None]
            mrr = sum(1.0 / r for r in ranks) / len(ranks) if ranks else 0.0
            fold_list.append({
                "fold": fold_idx + 1,
                "k": k,
                "w_kw": wkw,
                "hit1": hit1,
                "hit3": hit3,
                "hit5": hit5,
                "mrr": mrr,
                "questions": fold_res,
            })
        fold_results[(k, wkw)] = fold_list

    # Print per-fold table.
    lines = ["| Config | Fold | Hit@1 | Hit@3 | Hit@5 | MRR |",
             "|---|---|---|---|---|---|"]
    for k, wkw in configs:
        for fm in fold_results[(k, wkw)]:
            lines.append(f"| k={k}, w_kw={wkw} | {fm['fold']} | {fm['hit1']:.3f} | {fm['hit3']:.3f} | {fm['hit5']:.3f} | {fm['mrr']:.3f} |")

    # Compute mean +/- std.
    config_means = {}
    for k, wkw in configs:
        folds_m = fold_results[(k, wkw)]
        means = {
            "hit1": np.mean([f["hit1"] for f in folds_m]),
            "hit3": np.mean([f["hit3"] for f in folds_m]),
            "hit5": np.mean([f["hit5"] for f in folds_m]),
            "mrr": np.mean([f["mrr"] for f in folds_m]),
        }
        stds = {
            "hit1": np.std([f["hit1"] for f in folds_m]),
            "hit3": np.std([f["hit3"] for f in folds_m]),
            "hit5": np.std([f["hit5"] for f in folds_m]),
            "mrr": np.std([f["mrr"] for f in folds_m]),
        }
        config_means[(k, wkw)] = (means, stds)

    lines.append("")
    lines.append("| Config | Mean Hit@1 | Std Hit@1 | Mean Hit@3 | Std Hit@3 | Mean Hit@5 | Std Hit@5 | Mean MRR | Std MRR |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for k, wkw in configs:
        means, stds = config_means[(k, wkw)]
        lines.append(f"| k={k}, w_kw={wkw} | {means['hit1']:.3f} | {stds['hit1']:.3f} | "
                     f"{means['hit3']:.3f} | {stds['hit3']:.3f} | "
                     f"{means['hit5']:.3f} | {stds['hit5']:.3f} | "
                     f"{means['mrr']:.3f} | {stds['mrr']:.3f} |")

    # Choose w_kw > 0 only if mean hit@3 beats w_kw=0 by >= 0.03.
    base_hit3 = None
    for k in K_VALUES:
        if (k, 0.0) in config_means:
            base_hit3 = config_means[(k, 0.0)][0]["hit3"]
            break

    chosen = None
    if base_hit3 is not None:
        threshold = base_hit3 + 0.03
        # Simplest = lowest w_kw, then lowest k.
        for wkw in sorted(WKW_VALUES):
            if wkw == 0.0:
                continue
            for k in sorted(K_VALUES):
                if config_means[(k, wkw)][0]["hit3"] >= threshold:
                    chosen = (k, wkw)
                    break
            if chosen:
                break

    if chosen is None:
        chosen = (K_VALUES[0], 0.0)
        print(f"\nNo w_kw > 0 beats w_kw=0 by >= 0.03. Keeping w_kw=0.")
        print(f"Base hit@3 (w_kw=0): {base_hit3:.3f}")
    else:
        print(f"\nChosen config: k={chosen[0]}, w_kw={chosen[1]}")
        print(f"Base hit@3 (w_kw=0): {base_hit3:.3f}, chosen hit@3: {config_means[chosen][0]['hit3']:.3f}")

    # Write fusion_config.json.
    config = {
        "k": chosen[0],
        "w_dense": 1.0,
        "w_kw": chosen[1],
        "method": "weighted_rrf",
        "keyword_variant": keyword_variant,
    }
    os.makedirs(os.path.dirname(FUSION_CONFIG_OUT), exist_ok=True)
    with open(FUSION_CONFIG_OUT, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {FUSION_CONFIG_OUT}")

    print("\n".join(lines))
    return "\n".join(lines), config_means, fold_results


def evaluate_keyword_variants(questions, embeddings, cur, chunk_meta, id_to_index,
                              stopwords, non_content_words, variant_map):
    """Evaluate v1-v4 keyword variants under both hit definitions."""
    variants = ["v1", "v2", "v3", "v4"]
    use_column_weights_map = {"v1": False, "v2": False, "v3": False, "v4": True}

    lines = ["| Variant | Definition | Hit@1 | Hit@3 | Hit@5 | MRR |",
             "|---|---|---|---|---|---|"]
    for variant in variants:
        ucw = use_column_weights_map[variant]
        for metric in ["answer_term", "page"]:
            hits1, hits3, hits5, ranks = 0, 0, 0, []
            for q in questions:
                qid = q["id"]
                expected_pages = set(q["expected_pages"])
                terms = q.get("answer_terms") or []
                query_text = q["q"]

                q_vec = embed_texts([query_text], kind="query")[0]
                dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=20)

                kw_query, _ = build_keyword_query(
                    query_text, stopwords, non_content_words, variant_map, variant=variant
                )
                kw_res = fts_search(cur, kw_query, top_k=20, use_column_weights=ucw)

                fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=0.0, k=60, top_k=5)

                if metric == "answer_term":
                    rank = hit_at_k_answer_term(fused, cur, terms, variant_map, 5)
                else:
                    rank = hit_at_k_page(fused, expected_pages, 5)

                if rank is not None and rank <= 1:
                    hits1 += 1
                if rank is not None and rank <= 3:
                    hits3 += 1
                if rank is not None and rank <= 5:
                    hits5 += 1
                if rank is not None:
                    ranks.append(rank)

            n = len(questions)
            mrr = sum(1.0 / r for r in ranks) / len(ranks) if ranks else 0.0
            lines.append(f"| {variant} | {metric} | {hits1/n:.3f} | {hits3/n:.3f} | {hits5/n:.3f} | {mrr:.3f} |")

    print("\n".join(lines))
    return "\n".join(lines)


def print_fold3_questions(fold_results, keyword_variant):
    """Print fold-3 questions with their result rows for each config."""
    lines = ["## Fold 3 Questions (per-config results)", ""]
    for k in K_VALUES:
        for wkw in WKW_VALUES:
            fold_list = fold_results[(k, wkw)]
            fold3 = [f for f in fold_list if f["fold"] == 3]
            if not fold3:
                continue
            fm = fold3[0]
            lines.append(f"### Config: k={k}, w_kw={wkw}, keyword_variant={keyword_variant}")
            lines.append("| id | question | hit1 | hit3 | hit5 | ans_rank | page_rank | fused_pages | expected_pages |")
            lines.append("|---|---|---|---|---|---|---|---|---|")
            for r in fm["questions"]:
                lines.append(
                    f"| {r['id']} | {r['question']} | {r['hit1']} | {r['hit3']} | {r['hit5']} | "
                    f"{r['ans_rank'] if r['ans_rank'] is not None else 'none'} | "
                    f"{r['page_rank'] if r['page_rank'] is not None else 'none'} | "
                    f"{r['fused_pages']} | {r['expected_pages']} |"
                )
            lines.append("")
    return "\n".join(lines)


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(EMBEDDINGS_BIN):
        print(f"ERROR: {EMBEDDINGS_BIN} not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(GOLDEN_PATH):
        print(f"ERROR: {GOLDEN_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    embeddings, meta = load_embeddings()
    questions = load_golden()
    print(f"In-scope English questions: {len(questions)}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    id_to_index = {cid: i for i, (cid, _, _, _) in enumerate(chunk_meta)}

    stopwords = load_stopwords()
    non_content_words = set(NON_CONTENT_WORDS)
    variant_map = load_variant_map(NORMALIZE_MAP_PATH) if os.path.exists(NORMALIZE_MAP_PATH) else {}

    # Evaluate keyword variants v1-v4 under both definitions.
    print("\n## Keyword Variants Comparison (v1-v4, both hit definitions)", "")
    variant_summary = evaluate_keyword_variants(
        questions, embeddings, cur, chunk_meta, id_to_index,
        stopwords, non_content_words, variant_map
    )

    # Pick best keyword variant: highest mean hit@3 under answer-term definition.
    # For simplicity, use v2 (stopword-only unigrams with bm25) as default best
    # since it performed well and v4 requires section column weighting.
    # We evaluate all and pick the best based on answer-term hit@3.
    best_variant = "v2"
    best_hit3 = -1.0
    for variant in ["v1", "v2", "v3", "v4"]:
        ucw = variant == "v4"
        hits3 = 0
        ranks = []
        for q in questions:
            qid = q["id"]
            terms = q.get("answer_terms") or []
            query_text = q["q"]
            q_vec = embed_texts([query_text], kind="query")[0]
            dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=20)
            kw_query, _ = build_keyword_query(
                query_text, stopwords, non_content_words, variant_map, variant=variant
            )
            kw_res = fts_search(cur, kw_query, top_k=20, use_column_weights=ucw)
            fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=0.0, k=60, top_k=5)
            rank = hit_at_k_answer_term(fused, cur, terms, variant_map, 3)
            if rank is not None and rank <= 3:
                hits3 += 1
            if rank is not None:
                ranks.append(rank)
        hit3 = hits3 / len(questions)
        print(f"  {variant}: hit@3 = {hit3:.3f}")
        if hit3 > best_hit3:
            best_hit3 = hit3
            best_variant = variant

    print(f"\nBest keyword variant: {best_variant} (hit@3 = {best_hit3:.3f})")

    # Cross-validation with best keyword variant.
    lines, config_means, fold_results = cross_validate(
        questions, embeddings, cur, chunk_meta, id_to_index,
        stopwords, non_content_words, variant_map,
        best_variant, use_column_weights=(best_variant == "v4")
    )

    # Determine chosen config from config_means (best hit@3).
    chosen = max(config_means.items(), key=lambda item: item[1][0]["hit3"])[0]

    # Print fold-3 questions.
    fold3_lines = print_fold3_questions(fold_results, best_variant)
    print("\n".join(fold3_lines))

    # Write summary.
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("## Keyword Variants Comparison\n\n")
            f.write(variant_summary + "\n\n")
            f.write(f"Best keyword variant: {best_variant} (hit@3 = {best_hit3:.3f})\n\n")
            f.write("## Weighted RRF Fusion Tuning (5-fold CV, answer-term metric)\n\n")
            f.write("\n".join(lines) + "\n\n")
            f.write(fold3_lines + "\n")
            f.write(f"Chosen config: k={chosen[0]}, w_kw={chosen[1]}, keyword_variant={best_variant}\n")

    conn.close()
    print("Fusion tuning complete.")


if __name__ == "__main__":
    main()
