#!/usr/bin/env python3
"""Latency benchmark for the embedding model.

Runs 5 warm-up queries, then 200 timed queries of varied length (3-25 words),
each timed individually. Reports mean, median, p95, p99, min, max for
intra_op_num_threads = 1 and = 4 (phone-like). Asserts p95 >= median.

This runs on the CI runner, NOT on a phone. Numbers are indicative only.
"""
import json
import os
import statistics
import sys
import time

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = os.path.join("app", "src", "main", "assets", "models", "embedder")
MODEL_PATH = os.path.join(MODEL_DIR, "model_quantized.onnx")
TOKENIZER_PATH = os.path.join(MODEL_DIR, "tokenizer.json")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")

MAX_LENGTH = 384
EMBED_DIM = 384
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

WARMUP = 5
N_QUERIES = 200


def load_meta():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        return json.load(f)


def create_session(threads):
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    return ort.InferenceSession(MODEL_PATH, sess_options=so, providers=["CPUExecutionProvider"])


def tokenize(tokenizer, text, max_length=MAX_LENGTH):
    enc = tokenizer.encode(text)
    ids = enc.ids[:max_length]
    mask = [1] * len(ids)
    pad = max_length - len(ids)
    ids += [0] * pad
    mask += [0] * pad
    return np.array([ids], dtype=np.int64), np.array([mask], dtype=np.int64), np.zeros((1, max_length), dtype=np.int64)


def mean_pool(last_hidden, mask):
    mask_f = mask.astype(np.float64)
    mask_sum = np.clip(np.sum(mask_f, axis=1, keepdims=True), 1e-9, None)
    masked = last_hidden.astype(np.float64) * mask_f[:, :, None]
    return np.sum(masked, axis=1) / mask_sum


def l2_normalize(v):
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n = np.clip(n, 1e-12, None)
    return v / n


def embed_one(session, tokenizer, text, kind="query"):
    prefix = QUERY_PREFIX if kind == "query" else PASSAGE_PREFIX
    input_ids, attention_mask, token_type_ids = tokenize(tokenizer, prefix + text)
    outputs = session.run(
        None,
        {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        },
    )
    pooled = mean_pool(outputs[0], attention_mask)
    return l2_normalize(pooled).astype(np.float32)[0]


def generate_queries(n=N_QUERIES, seed=7):
    """Generate varied-length queries from real chunk text."""
    import sqlite3

    DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = cur.execute("SELECT text FROM chunks ORDER BY id").fetchall()
    conn.close()

    rng = np.random.default_rng(seed)
    queries = []
    for _ in range(n):
        text = rng.choice(rows)[0]
        words = text.split()
        length = int(rng.integers(3, 26))  # 3 to 25 words
        start = int(rng.integers(0, max(1, len(words) - length + 1)))
        q = " ".join(words[start:start + length])
        queries.append(q)
    return queries


def benchmark(threads):
    session = create_session(threads)
    tokenizer = Tokenizer.from_file(TOKENIZER_PATH)

    # Warm-up
    warmup_queries = generate_queries(WARMUP, seed=99)
    for q in warmup_queries:
        embed_one(session, tokenizer, q)

    # Timed runs
    queries = generate_queries(N_QUERIES, seed=7)
    timings_ms = []
    for q in queries:
        t0 = time.perf_counter()
        embed_one(session, tokenizer, q)
        t1 = time.perf_counter()
        timings_ms.append((t1 - t0) * 1000.0)

    arr = np.array(timings_ms)
    return {
        "threads": threads,
        "count": len(timings_ms),
        "mean_ms": float(np.mean(arr)),
        "median_ms": float(np.median(arr)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "min_ms": float(np.min(arr)),
        "max_ms": float(np.max(arr)),
    }


def main():
    if not os.path.exists(MODEL_PATH):
        print(f"ERROR: {MODEL_PATH} not found. Run download_models.py first.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(EMBEDDINGS_META):
        print(f"ERROR: {EMBEDDINGS_META} not found. Run build_embeddings.py first.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(os.path.join("app", "src", "main", "assets", "books_knowledge.db")):
        print(f"ERROR: books_knowledge.db not found.", file=sys.stderr)
        sys.exit(1)

    meta = load_meta()
    print(f"Embedding model: {meta.get('model', 'unknown')}, dim={meta.get('dim', '?')}")

    results = []
    for threads in [1, 4]:
        r = benchmark(threads)
        results.append(r)
        # Assert p95 >= median
        assert r["p95_ms"] >= r["median_ms"], (
            f"p95 ({r['p95_ms']:.2f}) < median ({r['median_ms']:.2f}) for {threads} threads"
        )
        print(f"\nThreads={threads}:")
        print(f"  count={r['count']}  mean={r['mean_ms']:.2f} ms  median={r['median_ms']:.2f} ms")
        print(f"  p95={r['p95_ms']:.2f} ms  p99={r['p99_ms']:.2f} ms  min={r['min_ms']:.2f} ms  max={r['max_ms']:.2f} ms")

    # Summary table
    print("\n| Threads | Count | Mean (ms) | Median (ms) | p95 (ms) | p99 (ms) | Min (ms) | Max (ms) |")
    print("|---|---|---|---|---|---|---|---|")
    for r in results:
        print(f"| {r['threads']} | {r['count']} | {r['mean_ms']:.2f} | {r['median_ms']:.2f} | {r['p95_ms']:.2f} | {r['p99_ms']:.2f} | {r['min_ms']:.2f} | {r['max_ms']:.2f} |")

    print("\nNOTE: These timings are from the GitHub Actions CI runner, not a phone.")

    # Run check_determinism.py (Stage 3.7d-check)
    try:
        import check_determinism
        print("\n--- Running Determinism & Hardware Checks (Stage 3.7d-check) ---")
        check_determinism.main()
    except Exception as e:
        print(f"Warning: check_determinism failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
