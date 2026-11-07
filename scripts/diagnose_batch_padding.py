#!/usr/bin/env python3
"""Stage K4 Task 0: does int8 dynamic quantization make embeddings depend on
batch padding?

For every one of the 120 golden questions this script embeds the query text
with batch sizes 1, 8 and 16.  Tokenization truncates at 384 tokens and pads to
the longest sequence *in the current batch* (the same rule used by
``scripts/embedding_common.py``).  It then computes the top-1 dense cosine
(``s1``) against the already-built ``embeddings.bin`` matrix and reports:

  * max / mean |delta s1| between batch 1 and batch 8
  * max / mean |delta s1| between batch 1 and batch 16
  * max absolute embedding element delta and max L2 delta between 1 and 16
  * max / mean |delta s1| between this script's Python batch-1 s1 and Kotlin's
    s1 in the same job's ``build/reports/parity/retrieval_parity.csv``

Verdict: TRUE when max |delta s1| (batch 1 vs 16) or max absolute embedding
delta exceeds ``1e-5``.  The threshold is printed with the verdict so the
number is reproducible.

Outputs ``eval/batch_padding.csv`` and ``eval/batch_padding_summary.json``.
Does not modify ``build_embeddings.py``, the presets, or any asset used by the
pipeline.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate_signals import load_question_sets  # noqa: E402

ASSETS_DIR = os.path.join("app", "src", "main", "assets")
MODEL_DIR = os.path.join(ASSETS_DIR, "models", "embedder")
MODEL_PATH = os.path.join(MODEL_DIR, "model_quantized.onnx")
TOKENIZER_PATH = os.path.join(MODEL_DIR, "tokenizer.json")
EMBEDDINGS_BIN = os.path.join(ASSETS_DIR, "embeddings.bin")
EMBEDDINGS_META = os.path.join(ASSETS_DIR, "embeddings_meta.json")
PARITY_CSV = os.path.join("build", "reports", "parity", "retrieval_parity.csv")
OUT_CSV = os.path.join("eval", "batch_padding.csv")
OUT_SUMMARY = os.path.join("eval", "batch_padding_summary.json")

MAX_LENGTH = 384
EMBED_DIM = 384
QUERY_PREFIX = "query: "
BATCH_SIZES = (1, 8, 16)
PADDING_EPS = 1e-5


def load_chunk_matrix() -> np.ndarray:
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(meta["rows"], meta["dim"])
    if mat.shape[1] != EMBED_DIM:
        raise ValueError(f"expected {EMBED_DIM} dims, got {mat.shape[1]}")
    return mat


def tokenize_pad(tokenizer: Tokenizer, texts):
    """Truncate at 384 and pad to the longest sequence in this batch."""
    encodings = tokenizer.encode_batch(texts)
    max_len = min(MAX_LENGTH, max(len(e.ids) for e in encodings))
    input_ids = []
    attention_masks = []
    for enc in encodings:
        ids = list(enc.ids[:max_len])
        mask = [1] * len(ids)
        pad_len = max_len - len(ids)
        ids += [0] * pad_len
        mask += [0] * pad_len
        input_ids.append(ids)
        attention_masks.append(mask)
    return (
        np.asarray(input_ids, dtype=np.int64),
        np.asarray(attention_masks, dtype=np.int64),
    )


def mean_pool(last_hidden_state: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = attention_mask.astype(np.float64)
    mask_sum = np.clip(np.sum(mask, axis=1, keepdims=True), 1e-9, None)
    masked = last_hidden_state.astype(np.float64) * mask[:, :, None]
    return np.sum(masked, axis=1) / mask_sum


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)
    return vectors / norms


def embed_with_batch_size(
    texts, tokenizer: Tokenizer, session: ort.InferenceSession, batch_size: int
) -> np.ndarray:
    prefixed = [QUERY_PREFIX + t for t in texts]
    pieces = []
    for start in range(0, len(prefixed), batch_size):
        batch = prefixed[start:start + batch_size]
        input_ids, attention_mask = tokenize_pad(tokenizer, batch)
        outputs = session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": np.zeros_like(input_ids),
            },
        )
        pooled = mean_pool(outputs[0], attention_mask)
        pieces.append(l2_normalize(pooled).astype(np.float32))
    return np.vstack(pieces) if pieces else np.empty((0, EMBED_DIM), dtype=np.float32)


def exact_cosines(matrix: np.ndarray, matrix_norms: np.ndarray, vec: np.ndarray) -> np.ndarray:
    q = vec.astype(np.float64)
    qn = max(float(np.linalg.norm(q)), 1e-12)
    return (matrix @ q) / (matrix_norms * qn)


def load_parity(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    # In-scope and out-of-scope id ranges both start at 1, so key by
    # (cls, id) rather than id alone.
    by_key = {}
    for row in rows:
        try:
            by_key[(row["cls"], int(row["id"]))] = row
        except (KeyError, ValueError):
            continue
    return by_key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-missing-kotlin", action="store_true")
    args = parser.parse_args()

    for path in (MODEL_PATH, TOKENIZER_PATH, EMBEDDINGS_BIN, EMBEDDINGS_META):
        if not os.path.exists(path):
            print(f"ERROR: missing {path}", file=sys.stderr)
            return 1

    in_scope, out_of_scope = load_question_sets()
    questions = list(in_scope) + list(out_of_scope)
    texts = [q["q"] for q in questions]
    ids = [int(q["id"]) for q in questions]
    print(f"Questions: {len(texts)} ({len(in_scope)} in-scope, {len(out_of_scope)} out-of-scope)")

    tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
    session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])

    chunk_matrix = load_chunk_matrix().astype(np.float64)
    chunk_norms = np.linalg.norm(chunk_matrix, axis=1)

    vectors = {}
    s1 = {}
    top1 = {}
    for bs in BATCH_SIZES:
        print(f"Embedding with batch_size={bs} ...")
        vecs = embed_with_batch_size(texts, tokenizer, session, bs)
        vectors[bs] = vecs
        values = []
        chunks = []
        for vec in vecs:
            cos = exact_cosines(chunk_matrix, chunk_norms, vec)
            values.append(float(np.max(cos)))
            chunks.append(int(np.argmax(cos)) + 1)
        s1[bs] = np.asarray(values, dtype=np.float64)
        top1[bs] = chunks

    delta_1_8 = np.abs(s1[1] - s1[8])
    delta_1_16 = np.abs(s1[1] - s1[16])
    emb_abs_1_16 = np.abs(vectors[1].astype(np.float64) - vectors[16].astype(np.float64))
    emb_l2_1_16 = np.linalg.norm(
        vectors[1].astype(np.float64) - vectors[16].astype(np.float64), axis=1
    )

    parity = load_parity(PARITY_CSV)
    if parity is None and not args.allow_missing_kotlin:
        print(f"ERROR: {PARITY_CSV} not found (run the Kotlin parity test first)", file=sys.stderr)
        return 1

    rows = []
    kotlin_deltas = []
    parity_python_deltas = []
    for i, q in enumerate(questions):
        qid = ids[i]
        row = {
            "group": "in" if i < len(in_scope) else "out",
            "cls": "IN" if i < len(in_scope) else q.get("cls", "OOS"),
            "id": qid,
            "question": q["q"],
            "s1_batch1": f"{s1[1][i]:.9f}",
            "s1_batch8": f"{s1[8][i]:.9f}",
            "s1_batch16": f"{s1[16][i]:.9f}",
            "abs_delta_s1_1_8": f"{delta_1_8[i]:.12f}",
            "abs_delta_s1_1_16": f"{delta_1_16[i]:.12f}",
            "top1_chunk_batch1": top1[1][i],
            "top1_chunk_batch8": top1[8][i],
            "top1_chunk_batch16": top1[16][i],
            "max_abs_embedding_delta_1_16": f"{float(np.max(emb_abs_1_16[i])):.12f}",
            "l2_embedding_delta_1_16": f"{float(emb_l2_1_16[i]):.12f}",
            "parity_python_s1": "",
            "kotlin_s1": "",
            "abs_delta_python_batch1_kotlin": "",
            "abs_delta_python_batch16_kotlin": "",
        }
        cls_key = "IN" if i < len(in_scope) else q.get("cls", "OOS")
        if parity is not None and (cls_key, qid) in parity:
            prow = parity[(cls_key, qid)]
            try:
                py_s1 = float(prow["python_s1"])
                kt_s1 = float(prow["kotlin_s1"])
                row["parity_python_s1"] = f"{py_s1:.9f}"
                row["kotlin_s1"] = f"{kt_s1:.9f}"
                d1 = abs(float(s1[1][i]) - kt_s1)
                d16 = abs(float(s1[16][i]) - kt_s1)
                kotlin_deltas.append(d1)
                parity_python_deltas.append(d16)
                row["abs_delta_python_batch1_kotlin"] = f"{d1:.12f}"
                row["abs_delta_python_batch16_kotlin"] = f"{d16:.12f}"
            except (KeyError, ValueError):
                pass
        rows.append(row)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    max_1_8 = float(np.max(delta_1_8))
    mean_1_8 = float(np.mean(delta_1_8))
    max_1_16 = float(np.max(delta_1_16))
    mean_1_16 = float(np.mean(delta_1_16))
    emb_abs_max = float(np.max(emb_abs_1_16))
    emb_l2_max = float(np.max(emb_l2_1_16))
    padding_dependent = bool(max_1_16 > PADDING_EPS or emb_abs_max > PADDING_EPS)

    summary = {
        "questions": len(texts),
        "batch_sizes": list(BATCH_SIZES),
        "delta_s1_batch1_vs_batch8_max": max_1_8,
        "delta_s1_batch1_vs_batch8_mean": mean_1_8,
        "delta_s1_batch1_vs_batch16_max": max_1_16,
        "delta_s1_batch1_vs_batch16_mean": mean_1_16,
        "embedding_abs_max_batch1_vs_batch16": emb_abs_max,
        "embedding_l2_max_batch1_vs_batch16": emb_l2_max,
        "padding_eps": PADDING_EPS,
        "padding_dependent": padding_dependent,
        "kotlin_available": bool(kotlin_deltas),
    }
    if kotlin_deltas:
        summary["python_batch1_vs_kotlin_max"] = float(max(kotlin_deltas))
        summary["python_batch1_vs_kotlin_mean"] = float(np.mean(kotlin_deltas))
        summary["python_batch16_reference_vs_kotlin_max"] = float(max(parity_python_deltas))
        summary["python_batch16_reference_vs_kotlin_mean"] = float(np.mean(parity_python_deltas))
        summary["kotlin_rows_compared"] = len(kotlin_deltas)

    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print("\n=== Task 0: batch-padding diagnostic ===")
    print(f"batch 1 vs 8  : max |delta s1| = {max_1_8:.12f}  mean = {mean_1_8:.12f}")
    print(f"batch 1 vs 16 : max |delta s1| = {max_1_16:.12f}  mean = {mean_1_16:.12f}")
    print(f"embedding 1 vs 16: max abs element delta = {emb_abs_max:.12f}")
    print(f"embedding 1 vs 16: max L2 delta          = {emb_l2_max:.12f}")
    if kotlin_deltas:
        print(
            "Python batch 1 vs Kotlin (retrieval_parity.csv): "
            f"max |delta s1| = {summary['python_batch1_vs_kotlin_max']:.12f}  "
            f"mean = {summary['python_batch1_vs_kotlin_mean']:.12f}  "
            f"rows = {summary['kotlin_rows_compared']}"
        )
        print(
            "Python batch16 reference vs Kotlin (retrieval_parity.csv): "
            f"max |delta s1| = {summary['python_batch16_reference_vs_kotlin_max']:.12f}  "
            f"mean = {summary['python_batch16_reference_vs_kotlin_mean']:.12f}"
        )
    else:
        print("Python vs Kotlin comparison: NOT AVAILABLE (no retrieval_parity.csv)")
    print(
        f"VERDICT padding_dependent = {'TRUE' if padding_dependent else 'FALSE'} "
        f"(threshold {PADDING_EPS:g}; max |delta s1| {max_1_16:.12f}, "
        f"max embedding delta {emb_abs_max:.12f})"
    )
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
