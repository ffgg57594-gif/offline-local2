#!/usr/bin/env python3
"""Re-measurement on golden v3 (chunk-level labels).

Methods: dense, keyword (v1-v4), weighted RRF fusion with grid k in {10, 60}
x w_kw in {0, 0.25, 0.5, 1.0}, candidate pools of top-20 per list.

Hit definitions:
  STRICT hit at k = target_chunk_id or any alt_chunk_id is in top-k chunks.
  LENIENT hit = STRICT or a chunk adjacent (id +/- 1 in same page and book) is in top-k.
  Page de-duplication is NOT applied before measuring.

Reports Table 1 (dense + keyword v1-v4, STRICT and LENIENT) and
Table 2 (5-fold CV, all 8 fusion configs, per-fold and mean+/-std, STRICT).

Chooses w_kw > 0 only if mean STRICT hit@3 beats w_kw=0 by >= 0.03;
otherwise keeps w_kw=0. Writes assets/fusion_config.json.

Failure review: every question with no STRICT hit in top-5 under chosen config.
"""
import hashlib
import json
import os
import random
import re
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts  # noqa: E402
from keyword_builder import (  # noqa: E402
    build_keyword_query,
    fts_search,
    load_stopwords,
    load_variant_map,
)

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_PATH = os.path.join("eval", "golden_v3.draft.jsonl")
NORMALIZE_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")
FUSION_CONFIG_OUT = os.path.join("app", "src", "main", "assets", "fusion_config.json")

EMBED_DIM = 384
SEED = 7
K_VALUES = [10, 60]
WKW_VALUES = [0.0, 0.25, 0.5, 1.0]
N_FOLDS = 5
CANDIDATE_POOL = 20


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
    return [q for q in questions if q.get("in_scope", False)]


def dense_search(query_vec, embeddings, chunk_meta, top_k=CANDIDATE_POOL):
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((cid, name, page, text, float(scores[idx])))
    return results


def keyword_search(cur, query, stopwords, non_content_words, variant_map, variant, top_k=CANDIDATE_POOL):
    kw_query, _ = build_keyword_query(query, stopwords, non_content_words, variant_map, variant=variant)
    if not kw_query:
        return []
    return fts_search(cur, kw_query, top_k=top_k)


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


def strict_hit_at_k(results, target_chunk_id, alt_chunk_ids, k):
    """STRICT: target or any alt is in top-k."""
    valid_ids = {target_chunk_id} | set(alt_chunk_ids)
    for rank, r in enumerate(results[:k], start=1):
        if r[0] in valid_ids:
            return rank
    return None


def lenient_hit_at_k(results, target_chunk_id, alt_chunk_ids, chunk_index_by_id, k):
    """LENIENT: STRICT or adjacent chunk (id +/- 1 in same page and book)."""
    rank = strict_hit_at_k(results, target_chunk_id, alt_chunk_ids, k)
    if rank is not None:
        return rank
    target_row = chunk_index_by_id.get(target_chunk_id)
    if target_row is None:
        return None
    _, _, target_page, _ = target_row
    adjacent_ids = set()
    for delta in (-1, 1):
        adj_id = target_chunk_id + delta
        adj_row = chunk_index_by_id.get(adj_id)
        if adj_row is not None and adj_row[2] == target_page:
            adjacent_ids.add(adj_id)
    if not adjacent_ids:
        return None
    for rank, r in enumerate(results[:k], start=1):
        if r[0] in adjacent_ids:
            return rank
    return None


def snippet_centred(text, query, window=300):
    """~window chars centred on the sentence with most query-word overlap."""
    query_words = set(re.findall(r"\w+", query.lower()))
    sentences = re.split(r"(?<=[.!?])\s+", text)
    best_sent = ""
    best_score = -1
    for sent in sentences:
        sent_words = set(re.findall(r"\w+", sent.lower()))
        score = len(query_words & sent_words)
        if score > best_score:
            best_score = score
            best_sent = sent
    if not best_sent:
        return text[:window]
    idx = text.find(best_sent)
    if idx < 0:
        return best_sent[:window]
    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(best_sent) + window // 2)
    return text[start:end]


def recall_at_k(results_list, hit_func, k):
    hits = 0
    ranks = []
    for r in results_list:
        rank = hit_func(r)
        if rank is not None and rank <= k:
            hits += 1
        if rank is not None:
            ranks.append(rank)
    n = len(results_list)
    mrr = sum(1.0 / rk for rk in ranks) / len(ranks) if ranks else 0.0
    return hits / n, mrr, n


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
    bin_sha256 = hashlib.sha256(open(EMBEDDINGS_BIN, "rb").read()).hexdigest()
    chunk_sha256 = meta.get("chunk_texts_sha256", "unknown")
    print(f"embeddings.bin sha256: {bin_sha256}")
    print(f"chunk_texts_sha256 from meta: {chunk_sha256}")
    print(f"embeddings rows: {meta.get('rows', 'unknown')}, dim: {meta.get('dim', 'unknown')}")

    questions = load_golden()
    print(f"In-scope questions: {len(questions)}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    chunk_index_by_id = {row[0]: row for row in chunk_meta}

    variant_map = load_variant_map(NORMALIZE_MAP_PATH) if os.path.exists(NORMALIZE_MAP_PATH) else {}
    stopwords = load_stopwords()

    # Embed all questions.
    query_texts = [q["q"] for q in questions]
    query_vecs = embed_texts(query_texts, kind="query")

    # Pre-compute results for all questions and methods.
    question_data = {}
    for qi, q in enumerate(questions):
        qid = q["id"]
        target_id = q["target_chunk_id"]
        alt_ids = q.get("alt_chunk_ids") or []
        q_vec = query_vecs[qi]

        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=CANDIDATE_POOL)

        kw_by_variant = {}
        for variant in ["v1", "v2", "v3", "v4"]:
            kw_res = keyword_search(
                cur, q["q"], stopwords, set(), variant_map, variant, top_k=CANDIDATE_POOL
            )
            kw_by_variant[variant] = kw_res

        question_data[qid] = {
            "question": q,
            "target_id": target_id,
            "alt_ids": alt_ids,
            "dense": dense_res,
            "keyword": kw_by_variant,
        }

    # ---------- Table 1 ----------
    print("\n=== Table 1: Dense and Keyword Variants (STRICT and LENIENT) ===")
    t1_lines = ["| Method | Definition | Hit@1 | Hit@3 | Hit@5 | MRR | Count |",
                "|---|---|---|---|---|---|---|"]

    def eval_method(results_list, hit_func):
        r1, mrr, n = recall_at_k(results_list, hit_func, 1)
        r3, _, _ = recall_at_k(results_list, hit_func, 3)
        r5, _, _ = recall_at_k(results_list, hit_func, 5)
        return r1, r3, r5, mrr, n

    # Dense, STRICT.
    dense_strict_rows = []
    dense_lenient_rows = []
    for qid, data in question_data.items():
        target_id = data["target_id"]
        alt_ids = data["alt_ids"]
        dense_strict_rows.append({
            "results": data["dense"],
            "hit": lambda r, tid=target_id, aids=alt_ids: strict_hit_at_k(r, tid, aids, 5),
        })
        dense_lenient_rows.append({
            "results": data["dense"],
            "hit": lambda r, tid=target_id, aids=alt_ids: lenient_hit_at_k(r, tid, aids, chunk_index_by_id, 5),
        })

    r1, r3, r5, mrr, n = eval_method(dense_strict_rows, lambda r: r["hit"](r["results"]))
    t1_lines.append(f"| dense | STRICT | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} | {n} |")
    r1, r3, r5, mrr, n = eval_method(dense_lenient_rows, lambda r: r["hit"](r["results"]))
    t1_lines.append(f"| dense | LENIENT | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} | {n} |")

    # Keyword variants.
    for variant in ["v1", "v2", "v3", "v4"]:
        kw_strict_rows = []
        kw_lenient_rows = []
        for qid, data in question_data.items():
            target_id = data["target_id"]
            alt_ids = data["alt_ids"]
            kw_strict_rows.append({
                "results": data["keyword"][variant],
                "hit": lambda r, tid=target_id, aids=alt_ids: strict_hit_at_k(r, tid, aids, 5),
            })
            kw_lenient_rows.append({
                "results": data["keyword"][variant],
                "hit": lambda r, tid=target_id, aids=alt_ids: lenient_hit_at_k(r, tid, aids, chunk_index_by_id, 5),
            })

        r1, r3, r5, mrr, n = eval_method(kw_strict_rows, lambda r: r["hit"](r["results"]))
        t1_lines.append(f"| keyword v{variant} | STRICT | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} | {n} |")
        r1, r3, r5, mrr, n = eval_method(kw_lenient_rows, lambda r: r["hit"](r["results"]))
        t1_lines.append(f"| keyword v{variant} | LENIENT | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} | {n} |")

    print("\n".join(t1_lines))

    # ---------- Table 2: 5-fold CV ----------
    print("\n=== Table 2: 5-Fold Cross-Validation (STRICT metric) ===")
    rng = random.Random(SEED)
    indices = list(range(len(questions)))
    rng.shuffle(indices)
    fold_size = len(indices) // N_FOLDS
    folds = [indices[i * fold_size:(i + 1) * fold_size] for i in range(N_FOLDS - 1)]
    folds.append(indices[(N_FOLDS - 1) * fold_size:])

    cv_lines = ["| Config | Fold | Hit@1 | Hit@3 | Hit@5 | MRR |",
                "|---|---|---|---|---|---|"]
    config_fold_results = {}

    for fold_idx, fold_indices in enumerate(folds):
        fold_qids = [questions[i]["id"] for i in fold_indices]
        for k in K_VALUES:
            for wkw in WKW_VALUES:
                hits1, hits3, hits5, ranks = 0, 0, 0, []
                for qid in fold_qids:
                    data = question_data[qid]
                    target_id = data["target_id"]
                    alt_ids = data["alt_ids"]
                    dense_res = data["dense"]
                    kw_res = data["keyword"]["v2"]
                    fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=wkw, k=k, top_k=5)
                    rank = strict_hit_at_k(fused, target_id, alt_ids, 5)
                    if rank is not None:
                        if rank <= 1:
                            hits1 += 1
                        if rank <= 3:
                            hits3 += 1
                        if rank <= 5:
                            hits5 += 1
                        ranks.append(rank)
                n = len(fold_qids)
                mrr = sum(1.0 / rk for rk in ranks) / len(ranks) if ranks else 0.0
                cv_lines.append(
                    f"| k={k}, w_kw={wkw} | {fold_idx + 1} | "
                    f"{hits1 / n:.3f} | {hits3 / n:.3f} | {hits5 / n:.3f} | {mrr:.3f} |"
                )
                config_fold_results.setdefault((k, wkw), []).append({
                    "fold": fold_idx + 1,
                    "hit1": hits1 / n, "hit3": hits3 / n, "hit5": hits5 / n, "mrr": mrr,
                })

    print("\n".join(cv_lines))

    # Mean +/- std.
    print("\n| Config | Mean Hit@1 | Std Hit@1 | Mean Hit@3 | Std Hit@3 | Mean Hit@5 | Std Hit@5 | Mean MRR | Std MRR |")
    print("|---|---|---|---|---|---|---|---|---|")
    config_means = {}
    for k in K_VALUES:
        for wkw in WKW_VALUES:
            folds_m = config_fold_results[(k, wkw)]
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
            print(
                f"| k={k}, w_kw={wkw} | {means['hit1']:.3f} | {stds['hit1']:.3f} | "
                f"{means['hit3']:.3f} | {stds['hit3']:.3f} | "
                f"{means['hit5']:.3f} | {stds['hit5']:.3f} | "
                f"{means['mrr']:.3f} | {stds['mrr']:.3f} |"
            )

    # Choose config.
    base_hit3 = config_means[(K_VALUES[0], 0.0)][0]["hit3"]
    print(f"\nBase hit@3 (w_kw=0): {base_hit3:.3f}")
    threshold = base_hit3 + 0.03
    chosen = None
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
        print("No w_kw > 0 beats w_kw=0 by >= 0.03. Keeping w_kw=0.")
    else:
        print(f"Chosen config: k={chosen[0]}, w_kw={chosen[1]}")

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

    # ---------- Failure review ----------
    print("\n=== Failure Review (STRICT, top-5, chosen config) ===")
    k_chosen, wkw_chosen = chosen
    failures = []
    for qid, data in question_data.items():
        target_id = data["target_id"]
        alt_ids = data["alt_ids"]
        dense_res = data["dense"]
        kw_res = data["keyword"]["v2"]
        fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=wkw_chosen, k=k_chosen, top_k=5)
        rank = strict_hit_at_k(fused, target_id, alt_ids, 5)

        if rank is None:
            target_row = chunk_index_by_id.get(target_id)
            target_text = target_row[3] if target_row else "UNKNOWN"
            top3 = []
            for r in fused[:3]:
                r_text = chunk_index_by_id.get(r[0], (None, None, None, ""))[3] or ""
                top3.append((r[0], r[1], snippet_centred(r_text, data["question"]["q"], 300)))
            failures.append({
                "id": qid,
                "question": data["question"]["q"],
                "target_text": target_text[:300],
                "top3": top3,
            })

    print(f"Failures (no STRICT hit in top-5): {len(failures)}")
    for f in failures:
        print(f"\n--- Q{f['id']}: {f['question']} ---")
        print(f"Target chunk (first 300 chars): {f['target_text']}")
        print("Top-3 retrieved:")
        for cid, page, snippet in f["top3"]:
            print(f"  Chunk {cid} (page {page}): {snippet[:300]}")

    # Step summary.
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n## Golden v3 Re-measurement\n\n")
            f.write(f"In-scope questions: {len(questions)}\n")
            f.write(f"Chosen fusion config: k={chosen[0]}, w_kw={chosen[1]}\n")
            f.write(f"Base hit@3 (w_kw=0): {base_hit3:.3f}\n")
            f.write(f"Failures: {len(failures)}\n\n")
            f.write("### Table 1\n\n")
            f.write("\n".join(t1_lines) + "\n\n")
            f.write("### Table 2\n\n")
            f.write("\n".join(cv_lines) + "\n")

    conn.close()
    print("\nGolden v3 re-measurement complete.")


if __name__ == "__main__":
    main()
