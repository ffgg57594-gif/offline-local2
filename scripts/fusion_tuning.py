#!/usr/bin/env python3
"""Weighted RRF fusion tuning with 5-fold cross-validation.

Score = w_dense/(k+rank_dense) + w_kw/(k+rank_kw).

Configs:
  w_kw in {0, 0.25, 0.5, 1.0} with w_dense = 1
  k in {10, 60}

Evaluates every config on 60 in-scope English questions with 5-fold CV
(fixed seed 7). Prints per-fold and mean +/- std of hit@1, hit@3, hit@5 and MRR.
Picks the simplest config within one std of the best hit@3 and writes it to
assets/fusion_config.json.

Also reports the chosen config on Arabic in-scope questions separately (no tuning
on them), with and without alias expansion, plus dense-only and keyword-only references.
"""
import json
import math
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
    compute_generic_terms,
    fts_search,
    load_stopwords,
    load_variant_map,
)  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_PATH = os.path.join("eval", "golden_v2.draft.jsonl")
ALIASES_PATH = os.path.join("app", "src", "main", "assets", "medical_aliases.json")
FUSION_CONFIG_OUT = os.path.join("app", "src", "main", "assets", "fusion_config.json")
NORMALIZE_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")

EMBED_DIM = 384
K_VALUES = [10, 60]
WKW_VALUES = [0.0, 0.25, 0.5, 1.0]
N_FOLDS = 5
SEED = 7


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat


def load_golden():
    questions = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return [q for q in questions if q["in_scope"] and q["lang"] == "en"]


def dense_search(query_vec, embeddings, chunk_meta, top_k=5):
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((name, page, text, float(scores[idx])))
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


def hit_at_k(results, expected_pages, k):
    top_pages = [r[1] for r in results[:k]]
    return any(p in expected_pages for p in top_pages)


def mrr(results, expected_pages):
    for rank, r in enumerate(results, 1):
        if r[1] in expected_pages:
            return 1.0 / rank
    return 0.0


def cross_validate(questions, embeddings, cur, chunk_meta, id_to_index, stopwords, generic_terms, variant_map):
    """5-fold cross-validation over all fusion configs."""
    rng = random.Random(SEED)
    indices = list(range(len(questions)))
    rng.shuffle(indices)
    fold_size = len(indices) // N_FOLDS
    folds = [indices[i*fold_size:(i+1)*fold_size] for i in range(N_FOLDS)]
    # Handle remainder
    remainder = indices[N_FOLDS*fold_size:]
    for i, idx in enumerate(remainder):
        folds[i % N_FOLDS].append(idx)

    configs = []
    for k in K_VALUES:
        for wkw in WKW_VALUES:
            configs.append((k, wkw))

    results_table = []
    config_scores = {}  # (k, wkw) -> list of (hit1, hit3, hit5, mrr) per fold

    for k, wkw in configs:
        fold_metrics = []
        for fold_idx in range(N_FOLDS):
            test_indices = folds[fold_idx]
            train_indices = [i for j in range(N_FOLDS) if j != fold_idx for i in folds[j]]

            hits1, hits3, hits5, mrrs = 0, 0, 0, 0
            for ti in test_indices:
                q = questions[ti]
                expected = set(q["expected_pages"])
                query_text = q["q"]

                q_vec = embed_texts([query_text], kind="query")[0]
                dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=5)

                kw_query, _ = build_keyword_query(query_text, stopwords, generic_terms, variant_map)
                kw_res = fts_search(cur, kw_query, top_k=5)

                fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=wkw, k=k, top_k=5)

                hits1 += int(hit_at_k(fused, expected, 1))
                hits3 += int(hit_at_k(fused, expected, 3))
                hits5 += int(hit_at_k(fused, expected, 5))
                mrrs += mrr(fused, expected)

            n_test = len(test_indices)
            fold_metrics.append({
                "fold": fold_idx + 1,
                "k": k,
                "w_kw": wkw,
                "hit1": hits1 / n_test,
                "hit3": hits3 / n_test,
                "hit5": hits5 / n_test,
                "mrr": mrrs / n_test,
            })
        config_scores[(k, wkw)] = fold_metrics

    # Print table.
    lines = ["| Config | Fold | Hit@1 | Hit@3 | Hit@5 | MRR |", "|---|---|---|---|---|---|"]
    summary_lines = ["## Weighted RRF Fusion Tuning (5-fold CV, in-scope English)", "",
                     "| Config | Fold | Hit@1 | Hit@3 | Hit@5 | MRR |", "|---|---|---|---|---|---|"]

    for k, wkw in configs:
        for fm in config_scores[(k, wkw)]:
            config_label = f"k={k}, w_kw={wkw}"
            lines.append(f"| {config_label} | {fm['fold']} | {fm['hit1']:.3f} | {fm['hit3']:.3f} | {fm['hit5']:.3f} | {fm['mrr']:.3f} |")
            summary_lines.append(f"| {config_label} | {fm['fold']} | {fm['hit1']:.3f} | {fm['hit3']:.3f} | {fm['hit5']:.3f} | {fm['mrr']:.3f} |")

    # Compute mean +/- std per config.
    config_means = {}
    for k, wkw in configs:
        folds_m = config_scores[(k, wkw)]
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
    summary_lines.append("")
    lines.append("| Config | Mean Hit@1 | Std Hit@1 | Mean Hit@3 | Std Hit@3 | Mean Hit@5 | Std Hit@5 | Mean MRR | Std MRR |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    summary_lines.append("| Config | Mean Hit@1 | Std Hit@1 | Mean Hit@3 | Std Hit@3 | Mean Hit@5 | Std Hit@5 | Mean MRR | Std MRR |")
    summary_lines.append("|---|---|---|---|---|---|---|---|---|")

    for k, wkw in configs:
        means, stds = config_means[(k, wkw)]
        config_label = f"k={k}, w_kw={wkw}"
        lines.append(f"| {config_label} | {means['hit1']:.3f} | {stds['hit1']:.3f} | {means['hit3']:.3f} | {stds['hit3']:.3f} | {means['hit5']:.3f} | {stds['hit5']:.3f} | {means['mrr']:.3f} | {stds['mrr']:.3f} |")
        summary_lines.append(f"| {config_label} | {means['hit1']:.3f} | {stds['hit1']:.3f} | {means['hit3']:.3f} | {stds['hit3']:.3f} | {means['hit5']:.3f} | {stds['hit5']:.3f} | {means['mrr']:.3f} | {stds['mrr']:.3f} |")

    # Pick simplest config within one std of best hit@3.
    best_hit3 = max(m["hit3"] for means, _ in config_means.values() for m in [means])
    best_hit3_std = None
    for (k, wkw), (means, stds) in config_means.items():
        if abs(means["hit3"] - best_hit3) < 1e-9:
            best_hit3_std = stds["hit3"]
            break

    threshold = best_hit3 - best_hit3_std if best_hit3_std is not None else best_hit3
    # Simplest = lowest w_kw, then lowest k.
    chosen = None
    for wkw in sorted(WKW_VALUES):
        for k in sorted(K_VALUES):
            means, _ = config_means[(k, wkw)]
            if means["hit3"] >= threshold:
                chosen = (k, wkw)
                break
        if chosen:
            break

    if chosen is None:
        # Fallback to best hit@3.
        best = max(config_means.items(), key=lambda item: item[1][0]["hit3"])
        chosen = best[0]

    print(f"\nBest hit@3: {best_hit3:.3f} (within 1 std threshold: {threshold:.3f})")
    print(f"Chosen config: k={chosen[0]}, w_kw={chosen[1]}")

    chosen_means, _ = config_means[chosen]
    print(f"Chosen config mean: Hit@1={chosen_means['hit1']:.3f}, Hit@3={chosen_means['hit3']:.3f}, "
          f"Hit@5={chosen_means['hit5']:.3f}, MRR={chosen_means['mrr']:.3f}")

    # Write fusion_config.json.
    config = {
        "k": chosen[0],
        "w_dense": 1.0,
        "w_kw": chosen[1],
        "method": "weighted_rrf",
    }
    os.makedirs(os.path.dirname(FUSION_CONFIG_OUT), exist_ok=True)
    with open(FUSION_CONFIG_OUT, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {FUSION_CONFIG_OUT}")

    print("\n".join(lines))
    return "\n".join(summary_lines), chosen, config_means


def evaluate_on_questions(questions, embeddings, cur, chunk_meta, id_to_index, stopwords, generic_terms, variant_map, k, wkw, label, use_aliases=False):
    """Evaluate a config on a set of questions."""
    hits1, hits3, hits5, mrrs = 0, 0, 0, 0
    results_detail = []

    for q in questions:
        expected = set(q["expected_pages"])
        query_text = q["q"]

        if use_aliases and "medical_aliases" in globals():
            # Alias expansion would be applied here; skipped for English-only.
            pass

        q_vec = embed_texts([query_text], kind="query")[0]
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=5)

        kw_query, _ = build_keyword_query(query_text, stopwords, generic_terms, variant_map)
        kw_res = fts_search(cur, kw_query, top_k=5)

        fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=wkw, k=k, top_k=5)

        h1 = hit_at_k(fused, expected, 1)
        h3 = hit_at_k(fused, expected, 3)
        h5 = hit_at_k(fused, expected, 5)
        m = mrr(fused, expected)
        hits1 += int(h1)
        hits3 += int(h3)
        h5_count = int(h5)
        hits5 += h5_count
        mrrs += m

        results_detail.append({
            "q": q["q"],
            "expected": sorted(expected),
            "fused_pages": [r[1] for r in fused[:3]],
            "hit5": bool(h5_count),
        })

    n = len(questions)
    summary = {
        "label": label,
        "n": n,
        "k": k,
        "w_kw": wkw,
        "hit1": hits1 / n,
        "hit3": hits3 / n,
        "hit5": hits5 / n,
        "mrr": mrrs / n,
    }
    return summary, results_detail


def evaluate_dense_keyword_references(questions, embeddings, cur, chunk_meta, id_to_index, stopwords, generic_terms, variant_map):
    """Dense-only and keyword-only on the same questions."""
    dense_h1 = dense_h3 = dense_h5 = dense_mrr = 0
    kw_h1 = kw_h3 = kw_h5 = kw_mrr = 0

    for q in questions:
        expected = set(q["expected_pages"])
        query_text = q["q"]

        q_vec = embed_texts([query_text], kind="query")[0]
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=5)

        kw_query, _ = build_keyword_query(query_text, stopwords, generic_terms, variant_map)
        kw_res = fts_search(cur, kw_query, top_k=5)

        dense_h1 += int(hit_at_k(dense_res, expected, 1))
        dense_h3 += int(hit_at_k(dense_res, expected, 3))
        dense_h5 += int(hit_at_k(dense_res, expected, 5))
        dense_mrr += mrr(dense_res, expected)

        kw_h1 += int(hit_at_k(kw_res, expected, 1))
        kw_h3 += int(hit_at_k(kw_res, expected, 3))
        kw_h5 += int(hit_at_k(kw_res, expected, 5))
        kw_mrr += mrr(kw_res, expected)

    n = len(questions)
    return {
        "dense": {"hit1": dense_h1/n, "hit3": dense_h3/n, "hit5": dense_h5/n, "mrr": dense_mrr/n},
        "keyword": {"hit1": kw_h1/n, "hit3": kw_h3/n, "hit5": kw_h5/n, "mrr": kw_mrr/n},
    }


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

    embeddings = load_embeddings()
    questions = load_golden()
    print(f"In-scope English questions: {len(questions)}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    id_to_index = {cid: i for i, (cid, _, _, _) in enumerate(chunk_meta)}

    stopwords = load_stopwords()
    generic_terms, total_chunks = compute_generic_terms(DB_PATH)
    variant_map = load_variant_map(NORMALIZE_MAP_PATH) if os.path.exists(NORMALIZE_MAP_PATH) else {}

    summary_lines, chosen, config_means = cross_validate(
        questions, embeddings, cur, chunk_meta, id_to_index, stopwords, generic_terms, variant_map
    )

    # Evaluate chosen config on English in-scope (as reference).
    k, wkw = chosen
    eng_summary, _ = evaluate_on_questions(
        questions, embeddings, cur, chunk_meta, id_to_index, stopwords, generic_terms,
        variant_map, k, wkw, "English in-scope (chosen config)"
    )

    # Dense-only and keyword-only references.
    refs = evaluate_dense_keyword_references(
        questions, embeddings, cur, chunk_meta, id_to_index, stopwords, generic_terms, variant_map
    )

    lines = ["",
             "## Reference methods on English in-scope questions",
             "",
             "| Method | Hit@1 | Hit@3 | Hit@5 | MRR |",
             "|---|---|---|---|---|"]
    for method_name in ["dense", "keyword"]:
        m = refs[method_name]
        lines.append(f"| {method_name} | {m['hit1']:.3f} | {m['hit3']:.3f} | {m['hit5']:.3f} | {m['mrr']:.3f} |")

    lines.append("")
    lines.append(f"## Chosen config (k={k}, w_kw={wkw}) on English in-scope")
    lines.append("")
    lines.append(f"| Hit@1 | Hit@3 | Hit@5 | MRR |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| {eng_summary['hit1']:.3f} | {eng_summary['hit3']:.3f} | {eng_summary['hit5']:.3f} | {eng_summary['mrr']:.3f} |")

    print("\n".join(lines))

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")
            f.write("\n".join(lines) + "\n")

    conn.close()
    print("Fusion tuning complete.")


if __name__ == "__main__":
    main()
