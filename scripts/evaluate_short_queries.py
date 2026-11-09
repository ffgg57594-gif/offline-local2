#!/usr/bin/env python3
"""Stage K5d: Short-query study (MEASUREMENT ONLY).

Evaluates 60 short in-scope queries (1-4 words) and 30 short out-of-scope queries:
1. Retrieval metrics (target-only and same-page):
   - Dense hit@1, hit@3, hit@5
   - BM25 (FTS5) hit@1, hit@3, hit@5
   - RRF fusion (k in {10, 60}, w_kw in {0.0, 0.25, 0.5, 1.0}) hit@1, hit@3, hit@5
2. Gate evaluation under current balanced and strict presets:
   - Answerable accepted x/60
   - Out-of-scope rejected y/30
   - Distribution of s1, s3, s4 (min, median, max) vs full golden questions
   - Listing of every rejected short in-scope query
3. Prints all tables in full and the full query list with targets.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import sqlite3
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from embedding_common import embed_texts  # noqa: E402
from gate_rule import accept  # noqa: E402
from gate_signals import compute_signals  # noqa: E402
from keyword_builder import build_keyword_query, fts_search, load_stopwords  # noqa: E402
from text_normalize import load_variant_map  # noqa: E402

DB_PATH = ROOT / "app/src/main/assets/books_knowledge.db"
EMBEDDINGS_BIN = ROOT / "app/src/main/assets/embeddings.bin"
EMBEDDINGS_META = ROOT / "app/src/main/assets/embeddings_meta.json"
GATE_CONFIG_PATH = ROOT / "app/src/main/assets/gate_config.json"
SHORT_QUERIES_PATH = ROOT / "eval/short_queries.jsonl"
FULL_SIGNALS_PATH = ROOT / "eval/gate_signals.csv"
NORMALIZE_MAP_PATH = ROOT / "app/src/main/assets/normalize_map.json"
OUT_DIR = ROOT / "build/reports/k5d"

K_GRID = [10, 60]
W_KW_GRID = [0.0, 0.25, 0.5, 1.0]
CANDIDATE_POOL = 20


def load_embeddings_and_meta():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, book_id, page, text FROM chunks ORDER BY id")
    chunk_meta = cur.fetchall()
    conn.close()
    return mat, chunk_meta


def dense_search(query_vec: np.ndarray, embeddings: np.ndarray, chunk_meta, top_k=CANDIDATE_POOL):
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    return [
        (chunk_meta[i][0], chunk_meta[i][1], chunk_meta[i][2], chunk_meta[i][3], float(scores[i]))
        for i in top_idx
    ]


def keyword_search(cur, query: str, stopwords, variant_map, top_k=CANDIDATE_POOL):
    kw_query, _ = build_keyword_query(query, stopwords, set(), variant_map, variant="v2")
    if not kw_query:
        return []
    return fts_search(cur, kw_query, top_k=top_k)


def weighted_rrf(dense_results, kw_results, w_dense=1.0, w_kw=0.5, k=60, top_k=5):
    def dedupe(results):
        seen = set()
        out = []
        for r in results:
            key = (r[0], r[2])  # (chunk_id, page)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    d_list = dedupe(dense_results)
    k_list = dedupe(kw_results)

    scores = {}
    dense_keys = [(r[0], r[2]) for r in d_list]
    kw_keys = [(r[0], r[2]) for r in k_list]

    for rank, key in enumerate(dense_keys):
        scores[key] = scores.get(key, 0.0) + w_dense / (k + rank + 1)
    for rank, key in enumerate(kw_keys):
        scores[key] = scores.get(key, 0.0) + w_kw / (k + rank + 1)

    sorted_keys = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    return [(key[0], key[1], score) for key, score in sorted_keys]


def evaluate_retrieval_at_k(retrieved_items, target_chunk_id, target_page, k):
    """Returns (target_only_hit, same_page_hit) for top-k."""
    top = retrieved_items[:k]
    target_hit = any(item[0] == target_chunk_id for item in top)
    page_hit = any(item[1] == target_page for item in top) or target_hit
    return target_hit, page_hit


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(GATE_CONFIG_PATH, "r", encoding="utf-8") as f:
        gate_config = json.load(f)

    with open(SHORT_QUERIES_PATH, "r", encoding="utf-8") as f:
        all_queries = [json.loads(line) for line in f if line.strip()]

    in_scope = [q for q in all_queries if q.get("in_scope", False)]
    out_of_scope = [q for q in all_queries if not q.get("in_scope", False)]

    print(f"Loaded {len(all_queries)} short queries: {len(in_scope)} in-scope, {len(out_of_scope)} out-of-scope")

    # Connect to DB and load assets
    embeddings, chunk_meta = load_embeddings_and_meta()
    chunk_index = {c[0]: c for c in chunk_meta}  # id -> (id, book_id, page, text)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    stopwords = load_stopwords()
    variant_map = load_variant_map(str(NORMALIZE_MAP_PATH)) if NORMALIZE_MAP_PATH.exists() else {}

    # Precompute query embeddings for in-scope
    in_scope_texts = [q["q"] for q in in_scope]
    in_scope_vectors = embed_texts(in_scope_texts, kind="query")

    # 1. Retrieval study on 60 in-scope
    retrieval_data = []
    for q, vec in zip(in_scope, in_scope_vectors):
        dense_res = dense_search(vec, embeddings, chunk_meta, top_k=CANDIDATE_POOL)
        dense_fmt = [(r[0], r[1], r[2], r[3], r[4]) for r in dense_res]
        kw_res = keyword_search(cur, q["q"], stopwords, variant_map, top_k=CANDIDATE_POOL)
        # kw_res items: (chunk_id, book_id, page, text, rank)
        retrieval_data.append({
            "query": q,
            "dense": [(r[0], r[2]) for r in dense_fmt],  # (chunk_id, page)
            "kw": [(r[0], r[2]) for r in kw_res],        # (chunk_id, page)
            "dense_full": dense_fmt,
            "kw_full": kw_res,
        })

    # Configurations to evaluate
    methods = [("dense", None, None), ("bm25", None, None)]
    for k in K_GRID:
        for wkw in W_KW_GRID:
            methods.append((f"rrf_k{k}_w{wkw}", k, wkw))

    retrieval_results = {}
    for method_name, k_val, wkw_val in methods:
        t_hits = {1: 0, 3: 0, 5: 0}
        p_hits = {1: 0, 3: 0, 5: 0}
        total = len(in_scope)

        for item in retrieval_data:
            target_id = item["query"]["target_chunk_id"]
            target_page = item["query"]["page"]

            if method_name == "dense":
                retrieved = item["dense"]
            elif method_name == "bm25":
                retrieved = item["kw"]
            else:
                fused = weighted_rrf(
                    item["dense_full"], item["kw_full"],
                    w_dense=1.0, w_kw=wkw_val, k=k_val, top_k=5
                )
                retrieved = [(r[0], r[1]) for r in fused]

            for cutoff in [1, 3, 5]:
                t_hit, p_hit = evaluate_retrieval_at_k(retrieved, target_id, target_page, cutoff)
                if t_hit:
                    t_hits[cutoff] += 1
                if p_hit:
                    p_hits[cutoff] += 1

        retrieval_results[method_name] = {
            "target_only": {c: t_hits[c] / total for c in [1, 3, 5]},
            "same_page": {c: p_hits[c] / total for c in [1, 3, 5]},
            "target_only_counts": {c: t_hits[c] for c in [1, 3, 5]},
            "same_page_counts": {c: p_hits[c] for c in [1, 3, 5]},
            "total": total,
        }

    # 2. Gate evaluation under current balanced and strict presets
    bal_preset = gate_config["balanced"]
    str_preset = gate_config["strict"]

    in_scope_signals = []
    bal_accepted = []
    str_accepted = []
    bal_rejected = []
    str_rejected = []

    for q in in_scope:
        sig = compute_signals(q["q"], conn=conn, embeddings=embeddings, chunk_meta=chunk_meta)
        sig["id"] = q["id"]
        sig["q"] = q["q"]
        sig["target_chunk_id"] = q["target_chunk_id"]
        sig["page"] = q["page"]
        in_scope_signals.append(sig)

        is_bal = accept(sig["s1_top1"], sig["s3_cov_top3"], sig["s4_unknown"], bal_preset)
        is_str = accept(sig["s1_top1"], sig["s3_cov_top3"], sig["s4_unknown"], str_preset)

        if is_bal:
            bal_accepted.append(sig)
        else:
            bal_rejected.append(sig)

        if is_str:
            str_accepted.append(sig)
        else:
            str_rejected.append(sig)

    oos_signals = []
    bal_oos_rejected = []
    str_oos_rejected = []

    for q in out_of_scope:
        sig = compute_signals(q["q"], conn=conn, embeddings=embeddings, chunk_meta=chunk_meta)
        sig["id"] = q["id"]
        sig["q"] = q["q"]
        sig["category"] = q.get("category", "oos")
        oos_signals.append(sig)

        is_bal = accept(sig["s1_top1"], sig["s3_cov_top3"], sig["s4_unknown"], bal_preset)
        is_str = accept(sig["s1_top1"], sig["s3_cov_top3"], sig["s4_unknown"], str_preset)

        if not is_bal:
            bal_oos_rejected.append(sig)
        if not is_str:
            str_oos_rejected.append(sig)

    # 3. Full-question signals baseline (from eval/gate_signals.csv)
    full_in_signals = []
    full_oos_signals = []
    if FULL_SIGNALS_PATH.exists():
        with open(FULL_SIGNALS_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                s_dict = {
                    "s1_top1": float(r["s1_top1"]),
                    "s3_cov_top3": float(r["s3_cov_top3"]),
                    "s4_unknown": int(float(r["s4_unknown"])),
                }
                if r.get("group") == "in" or r.get("in_scope") == "true":
                    full_in_signals.append(s_dict)
                else:
                    full_oos_signals.append(s_dict)

    def dist(values):
        if not values:
            return {"min": 0.0, "median": 0.0, "max": 0.0}
        v = np.array(values, dtype=np.float64)
        return {
            "min": float(np.min(v)),
            "median": float(np.median(v)),
            "max": float(np.max(v)),
        }

    dist_short_in_s1 = dist([s["s1_top1"] for s in in_scope_signals])
    dist_short_in_s3 = dist([s["s3_cov_top3"] for s in in_scope_signals])
    dist_short_in_s4 = dist([s["s4_unknown"] for s in in_scope_signals])

    dist_full_in_s1 = dist([s["s1_top1"] for s in full_in_signals])
    dist_full_in_s3 = dist([s["s3_cov_top3"] for s in full_in_signals])
    dist_full_in_s4 = dist([s["s4_unknown"] for s in full_in_signals])

    dist_short_oos_s1 = dist([s["s1_top1"] for s in oos_signals])
    dist_short_oos_s3 = dist([s["s3_cov_top3"] for s in oos_signals])
    dist_short_oos_s4 = dist([s["s4_unknown"] for s in oos_signals])

    dist_full_oos_s1 = dist([s["s1_top1"] for s in full_oos_signals])
    dist_full_oos_s3 = dist([s["s3_cov_top3"] for s in full_oos_signals])
    dist_full_oos_s4 = dist([s["s4_unknown"] for s in full_oos_signals])

    # Build report text
    lines = [
        "# STAGE K5d: Short-Query Evaluation Study (Measurement Only)",
        "",
        "> Measurement study on 60 in-scope short queries (1-4 words) and 30 out-of-scope short queries.",
        "> No retrieval, presets, or app logic changed.",
        "",
        "## 1. Full Query List with Target Chunks (60 In-Scope)",
        "",
        "| ID | Query (1-4 words) | Words | Target Chunk ID | Page | Topic / Section |",
        "|---|---|---|---|---|---|",
    ]
    for q in in_scope:
        lines.append(f"| {q['id']:02d} | `{q['q']}` | {q.get('word_count', len(q['q'].split()))} | {q['target_chunk_id']} | {q['page']} | Obstetric & Gynecologic topic |")

    lines.extend([
        "",
        "## 2. Full Query List (30 Out-Of-Scope)",
        "",
        "| ID | Query (1-4 words) | Words | Category | Note |",
        "|---|---|---|---|---|",
    ])
    for q in out_of_scope:
        lines.append(f"| {q['id']:02d} | `{q['q']}` | {q.get('word_count', len(q['q'].split()))} | {q.get('category')} | Short non-book query |")

    lines.extend([
        "",
        "## 3. Retrieval Performance Table (Target-Only vs Same-Page Metrics)",
        "",
        "| Method | Config (k, w_kw) | Target Hit@1 | Target Hit@3 | Target Hit@5 | Same-Page Hit@1 | Same-Page Hit@3 | Same-Page Hit@5 |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for method_name, k_val, wkw_val in methods:
        res = retrieval_results[method_name]
        t = res["target_only"]
        p = res["same_page"]
        cfg_str = f"k={k_val}, w_kw={wkw_val}" if k_val is not None else "-"
        lines.append(
            f"| `{method_name}` | {cfg_str} | "
            f"{t[1]:.3f} ({res['target_only_counts'][1]}/{res['total']}) | "
            f"{t[3]:.3f} ({res['target_only_counts'][3]}/{res['total']}) | "
            f"{t[5]:.3f} ({res['target_only_counts'][5]}/{res['total']}) | "
            f"{p[1]:.3f} ({res['same_page_counts'][1]}/{res['total']}) | "
            f"{p[3]:.3f} ({res['same_page_counts'][3]}/{res['total']}) | "
            f"{p[5]:.3f} ({res['same_page_counts'][5]}/{res['total']}) |"
        )

    lines.extend([
        "",
        "## 4. Presets Acceptance and Rejection Table",
        "",
        f"- **Balanced Preset** (`t1={bal_preset['t1']}`, `t3={bal_preset['t3']:.6f}`, `k={bal_preset['k']}`)",
        f"- **Strict Preset** (`t1={str_preset['t1']}`, `t3={str_preset['t3']:.6f}`, `k={str_preset['k']}`)",
        "",
        "| Metric | Balanced Preset | Strict Preset | Total |",
        "|---|---|---|---|",
        f"| In-Scope Answerable Accepted | **{len(bal_accepted)} / 60** ({len(bal_accepted)/60*100:.1f}%) | **{len(str_accepted)} / 60** ({len(str_accepted)/60*100:.1f}%) | 60 |",
        f"| Out-Of-Scope Rejected | **{len(bal_oos_rejected)} / 30** ({len(bal_oos_rejected)/30*100:.1f}%) | **{len(str_oos_rejected)} / 30** ({len(str_oos_rejected)/30*100:.1f}%) | 30 |",
        "",
        "## 5. Signal Distribution Comparison: Short Queries vs Full Questions",
        "",
        "| Query Set | Signal | Min | Median | Max |",
        "|---|---|---|---|---|",
        f"| **Short In-Scope (60)** | `s1_top1` | {dist_short_in_s1['min']:.4f} | {dist_short_in_s1['median']:.4f} | {dist_short_in_s1['max']:.4f} |",
        f"| Full In-Scope (60) | `s1_top1` | {dist_full_in_s1['min']:.4f} | {dist_full_in_s1['median']:.4f} | {dist_full_in_s1['max']:.4f} |",
        f"| **Short In-Scope (60)** | `s3_cov_top3` | {dist_short_in_s3['min']:.4f} | {dist_short_in_s3['median']:.4f} | {dist_short_in_s3['max']:.4f} |",
        f"| Full In-Scope (60) | `s3_cov_top3` | {dist_full_in_s3['min']:.4f} | {dist_full_in_s3['median']:.4f} | {dist_full_in_s3['max']:.4f} |",
        f"| **Short In-Scope (60)** | `s4_unknown` | {dist_short_in_s4['min']:.1f} | {dist_short_in_s4['median']:.1f} | {dist_short_in_s4['max']:.1f} |",
        f"| Full In-Scope (60) | `s4_unknown` | {dist_full_in_s4['min']:.1f} | {dist_full_in_s4['median']:.1f} | {dist_full_in_s4['max']:.1f} |",
        "|---|---|---|---|---|",
        f"| **Short Out-Of-Scope (30)** | `s1_top1` | {dist_short_oos_s1['min']:.4f} | {dist_short_oos_s1['median']:.4f} | {dist_short_oos_s1['max']:.4f} |",
        f"| Full Out-Of-Scope (60) | `s1_top1` | {dist_full_oos_s1['min']:.4f} | {dist_full_oos_s1['median']:.4f} | {dist_full_oos_s1['max']:.4f} |",
        f"| **Short Out-Of-Scope (30)** | `s3_cov_top3` | {dist_short_oos_s3['min']:.4f} | {dist_short_oos_s3['median']:.4f} | {dist_short_oos_s3['max']:.4f} |",
        f"| Full Out-Of-Scope (60) | `s3_cov_top3` | {dist_full_oos_s3['min']:.4f} | {dist_full_oos_s3['median']:.4f} | {dist_full_oos_s3['max']:.4f} |",
        f"| **Short Out-Of-Scope (30)** | `s4_unknown` | {dist_short_oos_s4['min']:.1f} | {dist_short_oos_s4['median']:.1f} | {dist_short_oos_s4['max']:.1f} |",
        f"| Full Out-Of-Scope (60) | `s4_unknown` | {dist_full_oos_s4['min']:.1f} | {dist_full_oos_s4['median']:.1f} | {dist_full_oos_s4['max']:.1f} |",
        "",
        "## 6. List of Every Short In-Scope Query Rejected",
        "",
    ])

    lines.append(f"### Under Balanced Preset ({len(bal_rejected)} rejected):")
    if bal_rejected:
        lines.append("| ID | Query | Target Chunk ID | Page | `s1_top1` | `s3_cov_top3` | `s4_unknown` | Rejection Reason |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for s in bal_rejected:
            reasons = []
            if s["s1_top1"] < bal_preset["t1"]:
                reasons.append(f"s1 ({s['s1_top1']:.4f}) < {bal_preset['t1']}")
            if s["s3_cov_top3"] < bal_preset["t3"]:
                reasons.append(f"s3 ({s['s3_cov_top3']:.4f}) < {bal_preset['t3']:.4f}")
            if s["s4_unknown"] > bal_preset["k"]:
                reasons.append(f"s4 ({s['s4_unknown']}) > {bal_preset['k']}")
            lines.append(f"| {s['id']:02d} | `{s['q']}` | {s['target_chunk_id']} | {s['page']} | {s['s1_top1']:.4f} | {s['s3_cov_top3']:.4f} | {s['s4_unknown']} | {', '.join(reasons)} |")
    else:
        lines.append("- None! All 60 short in-scope queries accepted under Balanced preset.")

    lines.append("")
    lines.append(f"### Under Strict Preset ({len(str_rejected)} rejected):")
    if str_rejected:
        lines.append("| ID | Query | Target Chunk ID | Page | `s1_top1` | `s3_cov_top3` | `s4_unknown` | Rejection Reason |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for s in str_rejected:
            reasons = []
            if s["s1_top1"] < str_preset["t1"]:
                reasons.append(f"s1 ({s['s1_top1']:.4f}) < {str_preset['t1']}")
            if s["s3_cov_top3"] < str_preset["t3"]:
                reasons.append(f"s3 ({s['s3_cov_top3']:.4f}) < {str_preset['t3']:.4f}")
            if s["s4_unknown"] > str_preset["k"]:
                reasons.append(f"s4 ({s['s4_unknown']}) > {str_preset['k']}")
            lines.append(f"| {s['id']:02d} | `{s['q']}` | {s['target_chunk_id']} | {s['page']} | {s['s1_top1']:.4f} | {s['s3_cov_top3']:.4f} | {s['s4_unknown']} | {', '.join(reasons)} |")
    else:
        lines.append("- None! All 60 short in-scope queries accepted under Strict preset.")

    report_text = "\n".join(lines) + "\n"
    (OUT_DIR / "short_queries_report.md").write_text(report_text, encoding="utf-8")
    k5b_dir = ROOT / "build/reports/k5b"
    k5b_dir.mkdir(parents=True, exist_ok=True)
    (k5b_dir / "short_queries_report.md").write_text(report_text, encoding="utf-8")

    json_report = {
        "retrieval": retrieval_results,
        "balanced": {
            "accepted_count": len(bal_accepted),
            "accepted_pct": len(bal_accepted) / 60,
            "oos_rejected_count": len(bal_oos_rejected),
            "oos_rejected_pct": len(bal_oos_rejected) / 30,
            "rejected_in_scope": bal_rejected,
        },
        "strict": {
            "accepted_count": len(str_accepted),
            "accepted_pct": len(str_accepted) / 60,
            "oos_rejected_count": len(str_oos_rejected),
            "oos_rejected_pct": len(str_oos_rejected) / 30,
            "rejected_in_scope": str_rejected,
        },
        "distributions": {
            "short_in": {"s1": dist_short_in_s1, "s3": dist_short_in_s3, "s4": dist_short_in_s4},
            "full_in": {"s1": dist_full_in_s1, "s3": dist_full_in_s3, "s4": dist_full_in_s4},
            "short_oos": {"s1": dist_short_oos_s1, "s3": dist_short_oos_s3, "s4": dist_short_oos_s4},
            "full_oos": {"s1": dist_full_oos_s1, "s3": dist_full_oos_s3, "s4": dist_full_oos_s4},
        },
    }
    json_report_str = json.dumps(json_report, indent=2) + "\n"
    (OUT_DIR / "short_queries_report.json").write_text(
        json_report_str, encoding="utf-8"
    )
    (k5b_dir / "short_queries_report.json").write_text(
        json_report_str, encoding="utf-8"
    )

    print(report_text)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report_text + "\n")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
