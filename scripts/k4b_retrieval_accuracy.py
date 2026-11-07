#!/usr/bin/env python3
"""K4b: retrieval accuracy on the original sampled chunks, batch 16 vs batch 1.

The labels are the 60 chunks in ``eval/chunks_for_golden.jsonl`` (the same
chunks from which the golden-v3 in-scope questions were authored).  No
alt_chunk_ids are used: a hit is the sampled chunk itself, its page, or a page
within one page of it.

Two complete pipelines are evaluated:

  old: corpus embeddings built with padding-aware batch size 16, and query
       embeddings also computed with batch size 16;
  new: corpus embeddings built with batch size 1 (no padding), and query
       embeddings also computed with batch size 1.

Outputs:
  build/reports/k4b/retrieval_accuracy.csv
  build/reports/k4b/retrieval_accuracy.json
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
CHUNKS_GOLDEN = os.path.join("eval", "chunks_for_golden.jsonl")
GOLDEN_V3 = os.path.join("eval", "golden_v3.draft.jsonl")
K4B_DIR = os.path.join("build", "reports", "k4b")
BATCH16_BIN = os.path.join(K4B_DIR, "embeddings_batch16.bin")
OUT_CSV = os.path.join(K4B_DIR, "retrieval_accuracy.csv")
OUT_JSON = os.path.join(K4B_DIR, "retrieval_accuracy.json")

TOP_K = 5
KS = (1, 3, 5)


def load_matrix(path: str) -> np.ndarray:
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    return np.fromfile(path, dtype=np.float32).reshape(meta["rows"], meta["dim"])


def load_targets():
    sampled = []
    with open(CHUNKS_GOLDEN, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                sampled.append(json.loads(line))

    questions_by_target = {}
    with open(GOLDEN_V3, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("in_scope") is True:
                target = int(obj["target_chunk_id"])
                if target in questions_by_target:
                    raise ValueError(f"duplicate target_chunk_id {target} in {GOLDEN_V3}")
                questions_by_target[target] = obj

    rows = []
    for item in sampled:
        cid = int(item["id"])
        if cid not in questions_by_target:
            raise ValueError(f"sampled chunk {cid} has no golden-v3 question")
        q = questions_by_target[cid]
        rows.append({
            "target_chunk_id": cid,
            "target_page": int(item["page"]),
            "id": int(q["id"]),
            "question": q["q"],
        })
    if len(rows) != 60:
        raise ValueError(f"expected 60 sampled chunks, got {len(rows)}")
    return rows


def top_k_ids(scores: np.ndarray, k: int) -> np.ndarray:
    return np.argsort(-scores, kind="stable")[:k]


def evaluate(embeddings: np.ndarray, query_vectors: np.ndarray, rows, chunk_ids, chunk_pages):
    norms = np.linalg.norm(embeddings, axis=1)
    out = {f"{method}@{k}": 0 for method in ("exact_chunk", "same_page", "page_pm1") for k in KS}
    for i, row in enumerate(rows):
        q = query_vectors[i].astype(np.float64)
        scores = (embeddings.astype(np.float64) @ q) / np.clip(norms, 1e-12, None)
        order = top_k_ids(scores, TOP_K)
        top_ids = [int(chunk_ids[j]) for j in order]
        top_pages = [int(chunk_pages[j]) for j in order]
        target_id = row["target_chunk_id"]
        target_page = row["target_page"]
        for k in KS:
            if target_id in top_ids[:k]:
                out[f"exact_chunk@{k}"] += 1
            if target_page in top_pages[:k]:
                out[f"same_page@{k}"] += 1
            if any(abs(p - target_page) <= 1 for p in top_pages[:k]):
                out[f"page_pm1@{k}"] += 1
    return out


def main() -> int:
    for path in (DB_PATH, EMBEDDINGS_BIN, EMBEDDINGS_META, CHUNKS_GOLDEN, GOLDEN_V3):
        if not os.path.exists(path):
            print(f"ERROR: missing {path}", file=sys.stderr)
            return 1

    if not os.path.exists(BATCH16_BIN):
        print(
            f"ERROR: {BATCH16_BIN} not found; run scripts/build_embeddings.py first "
            "(it writes the batch-16 diagnostic matrix).",
            file=sys.stderr,
        )
        return 1

    conn = sqlite3.connect(DB_PATH)
    chunk_meta = conn.execute("SELECT id, page FROM chunks ORDER BY id").fetchall()
    conn.close()
    chunk_ids = [c[0] for c in chunk_meta]
    chunk_pages = [c[1] for c in chunk_meta]

    rows = load_targets()
    questions = [r["question"] for r in rows]

    emb_new = load_matrix(EMBEDDINGS_BIN)
    emb_old = load_matrix(BATCH16_BIN)
    if emb_new.shape != emb_old.shape:
        print("ERROR: batch-1 and batch-16 matrices have different shapes", file=sys.stderr)
        return 1

    print(f"Questions: {len(rows)} (one per sampled chunk)")
    print("Embedding queries with old batch size 16 ...")
    q_old = embed_texts(questions, kind="query", batch_size=16)
    print("Embedding queries with new batch size 1 ...")
    q_new = embed_texts(questions, kind="query", batch_size=1)

    old = evaluate(emb_old, q_old, rows, chunk_ids, chunk_pages)
    new = evaluate(emb_new, q_new, rows, chunk_ids, chunk_pages)

    methods = [
        ("exact_chunk", "exact sampled chunk"),
        ("same_page", "same page"),
        ("page_pm1", "page +/- 1"),
    ]

    os.makedirs(K4B_DIR, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["method", "k", "old_hits", "old_rate", "new_hits", "new_rate", "delta_rate"])
        for method, _ in methods:
            for k in KS:
                key = f"{method}@{k}"
                w.writerow([
                    method, k, old[key], f"{old[key] / len(rows):.6f}",
                    new[key], f"{new[key] / len(rows):.6f}",
                    f"{(new[key] - old[key]) / len(rows):.6f}",
                ])

    summary = {
        "questions": len(rows),
        "top_k": TOP_K,
        "old": {"corpus_batch_size": 16, "query_batch_size": 16, "hits": old},
        "new": {"corpus_batch_size": 1, "query_batch_size": 1, "hits": new},
        "improved": {
            key: new[key] > old[key]
            for key in old
        },
        "worsened": {
            key: new[key] < old[key]
            for key in old
        },
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print("\n| Method | Hit@1 old | Hit@1 new | Hit@3 old | Hit@3 new | Hit@5 old | Hit@5 new |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for method, _ in methods:
        print(
            f"| {method} | "
            f"{old[f'{method}@1']}/60 | {new[f'{method}@1']}/60 | "
            f"{old[f'{method}@3']}/60 | {new[f'{method}@3']}/60 | "
            f"{old[f'{method}@5']}/60 | {new[f'{method}@5']}/60 |"
        )

    improved = [k for k in old if new[k] > old[k]]
    worsened = [k for k in old if new[k] < old[k]]
    print(f"\nImproved metrics (new > old): {improved if improved else 'none'}")
    print(f"Worsened metrics (new < old): {worsened if worsened else 'none'}")
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
