#!/usr/bin/env python3
"""Build embeddings.bin from all chunks in books_knowledge.db.

Reads chunks ordered by id, embeds each with "passage: " prefix using the
quantized ONNX model, mean-pools + L2-normalizes, and writes:
  app/src/main/assets/embeddings.bin      raw float32 LE matrix [N, 384]
  app/src/main/assets/embeddings_meta.json metadata

Safety asserts (exit 1 with clear message):
  rows == chunks_count
  no NaN/Inf
  every row norm within 1e-3 of 1.0
  file size == rows * 384 * 4
"""
import hashlib
import json
import os
import sqlite3
import sys
import time

import numpy as np

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
OUT_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
OUT_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
K4B_DIR = os.path.join("build", "reports", "k4b")
DIAG_BIN16 = os.path.join(K4B_DIR, "embeddings_batch16.bin")
DIAG_JSON = os.path.join(K4B_DIR, "embeddings_diagnostic.json")
TIME_JSON = os.path.join(K4B_DIR, "embedding_step_time.json")

EMBED_DIM = 384
PASSAGE_PREFIX = "passage: "

# Import from embedding_common in the scripts directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts, EMBED_DIM as _EC_DIM, PASSAGE_PREFIX as _EC_PREFIX  # noqa: E402

assert _EC_DIM == EMBED_DIM
assert _EC_PREFIX == PASSAGE_PREFIX


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run build_knowledge_db.py first.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    chunks_count = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    if chunks_count == 0:
        print("ERROR: No chunks in books_knowledge.db.", file=sys.stderr)
        sys.exit(1)

    rows = cur.execute("SELECT id, text FROM chunks ORDER BY id").fetchall()
    conn.close()

    chunk_ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]

    # Compute sha256 over all chunk texts for integrity check.
    all_texts_sha256 = hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()

    # Verify ids are sequential starting at 1.
    expected_ids = list(range(1, chunks_count + 1))
    if chunk_ids != expected_ids:
        print(f"ERROR: Chunk ids are not sequential 1..{chunks_count}.", file=sys.stderr)
        sys.exit(1)

    # Track truncation: we need to know how many chunks were truncated at 384 tokens.
    # Re-tokenize to count. Use embedding_common's tokenizer directly.
    import onnxruntime as ort
    from tokenizers import Tokenizer

    MODEL_DIR = os.path.join("app", "src", "main", "assets", "models", "embedder")
    tokenizer = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))

    truncated_count = 0
    longest_token_length = 0
    for text in texts:
        enc = tokenizer.encode(PASSAGE_PREFIX + text)
        longest_token_length = max(longest_token_length, len(enc.ids))
        if len(enc.ids) > 384:
            truncated_count += 1

    print(f"Chunks: {chunks_count}")
    print(f"Truncated at 384 tokens: {truncated_count}")
    print(f"Longest tokenized length: {longest_token_length}")

    # Embed all texts as passages. K4b: batch size 1, no padding within a batch.
    embed_start = time.perf_counter()
    embeddings = embed_texts(texts, kind="passage", batch_size=1)  # [N, 384] float32
    embedding_seconds = time.perf_counter() - embed_start
    print(
        f"Embedding step (batch_size=1): {embedding_seconds:.3f} s "
        f"for {chunks_count} chunks"
    )

    # Safety asserts.
    if embeddings.shape[0] != chunks_count:
        print(f"ERROR: rows {embeddings.shape[0]} != chunks_count {chunks_count}", file=sys.stderr)
        sys.exit(1)

    if np.any(np.isnan(embeddings)) or np.any(np.isinf(embeddings)):
        print("ERROR: NaN or Inf found in embeddings.", file=sys.stderr)
        sys.exit(1)

    norms = np.linalg.norm(embeddings, axis=1)
    norm_deviation = np.max(np.abs(norms - 1.0))
    if norm_deviation > 1e-3:
        print(f"ERROR: Row norm deviation {norm_deviation} > 1e-3", file=sys.stderr)
        sys.exit(1)

    # Write raw float32 little-endian binary.
    embeddings = np.ascontiguousarray(embeddings, dtype=np.float32)
    embeddings.tofile(OUT_BIN)

    file_size = os.path.getsize(OUT_BIN)
    expected_size = chunks_count * EMBED_DIM * 4
    if file_size != expected_size:
        print(f"ERROR: File size {file_size} != expected {expected_size}", file=sys.stderr)
        sys.exit(1)

    # Write meta JSON.
    meta = {
        "dim": EMBED_DIM,
        "rows": chunks_count,
        "dtype": "float32",
        "model": "multilingual-e5-small-quantized",
        "max_length": 384,
        "passage_prefix": PASSAGE_PREFIX,
        "query_prefix": "query: ",
        "sha256": sha256_file(OUT_BIN),
        "size_bytes": file_size,
        "chunk_texts_sha256": all_texts_sha256,
    }
    with open(OUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {OUT_BIN}: {file_size} bytes ({chunks_count} rows x {EMBED_DIM} dims)")
    print(f"Wrote {OUT_META}")
    print(f"Max row-norm deviation from 1.0: {norm_deviation:.6e}")

    # K4b: quantify the old batch-16 padding behaviour over the full corpus.
    # This does not touch the asset written above; it only writes a diagnostic
    # matrix and summary under build/reports/k4b/.
    print("\nK4b diagnostic: re-embedding all passages with the old batch size 16 ...")
    batch16_start = time.perf_counter()
    embeddings_batch16 = embed_texts(texts, kind="passage", batch_size=16)
    batch16_seconds = time.perf_counter() - batch16_start

    a = embeddings.astype(np.float64)
    b = embeddings_batch16.astype(np.float64)
    element_delta = np.abs(a - b)
    dot = np.sum(a * b, axis=1)
    norms_a = np.linalg.norm(a, axis=1)
    norms_b = np.linalg.norm(b, axis=1)
    cosines = dot / np.clip(norms_a * norms_b, 1e-12, None)

    max_element_delta = float(np.max(element_delta))
    min_cosine = float(np.min(cosines))
    mean_cosine = float(np.mean(cosines))

    os.makedirs(K4B_DIR, exist_ok=True)
    np.ascontiguousarray(embeddings_batch16, dtype=np.float32).tofile(DIAG_BIN16)
    diagnostic = {
        "chunks": chunks_count,
        "dim": EMBED_DIM,
        "batch_size_new": 1,
        "batch_size_old": 16,
        "max_element_delta_batch1_vs_batch16": max_element_delta,
        "min_cosine_batch1_vs_batch16": min_cosine,
        "mean_cosine_batch1_vs_batch16": mean_cosine,
        "embedding_step_seconds_batch1": embedding_seconds,
        "embedding_step_seconds_batch16": batch16_seconds,
        "batch16_bin": DIAG_BIN16,
        "batch16_bin_sha256": sha256_file(DIAG_BIN16),
        "batch1_bin_sha256": sha256_file(OUT_BIN),
    }
    with open(DIAG_JSON, "w", encoding="utf-8") as f:
        json.dump(diagnostic, f, indent=2)
        f.write("\n")
    with open(TIME_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {
                "batch_size": 1,
                "chunks": chunks_count,
                "seconds": embedding_seconds,
            },
            f,
            indent=2,
        )
        f.write("\n")

    print(f"Passage embeddings compared: {chunks_count} chunks")
    print(f"max element delta (batch 1 vs batch 16): {max_element_delta:.12f}")
    print(f"min cosine (batch 1 vs batch 16): {min_cosine:.12f}")
    print(f"mean cosine (batch 1 vs batch 16): {mean_cosine:.12f}")
    print(f"batch 16 diagnostic embedding time: {batch16_seconds:.3f} s")
    print(f"Wrote {DIAG_BIN16}")
    print(f"Wrote {DIAG_JSON}")
    print(f"Wrote {TIME_JSON}")
    print("Embeddings build complete.")


if __name__ == "__main__":
    main()
