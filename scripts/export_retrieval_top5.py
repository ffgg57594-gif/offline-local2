#!/usr/bin/env python3
"""Stage 3.7f: Export dense top-5 retrieval for all 120 questions.

Writes eval/retrieval_top5.csv with:
  group, cls, id, question,
  rank_1_chunk_id, rank_1_page, rank_1_dense_cosine,
  rank_2_chunk_id, rank_2_page, rank_2_dense_cosine,
  rank_3_chunk_id, rank_3_page, rank_3_dense_cosine,
  rank_4_chunk_id, rank_4_page, rank_4_dense_cosine,
  rank_5_chunk_id, rank_5_page, rank_5_dense_cosine,
  target_chunk_id, alt_chunk_ids
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import onnxruntime as ort

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts  # noqa: E402
from gate_signals import load_question_sets  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_PATH = os.path.join("eval", "golden_v3.draft.jsonl")
OUT_CSV = os.path.join("eval", "retrieval_top5.csv")
OUT_META = os.path.join("eval", "retrieval_top5.meta.json")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def cpu_model():
    """Return the first CPU model string reported by the host."""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                k = key.strip().lower()
                if k in ("model name", "hardware", "model") and value.strip():
                    return value.strip()
    except OSError:
        pass
    try:
        out = subprocess.check_output(["lscpu"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() == "model name" and value.strip():
                return value.strip()
    except Exception:
        pass
    return platform.processor() or platform.machine() or "unknown"


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(EMBEDDINGS_BIN):
        print(f"ERROR: {EMBEDDINGS_BIN} not found.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute("SELECT id, page FROM chunks ORDER BY id").fetchall()
    chunk_ids = [c[0] for c in chunk_meta]
    chunk_pages = [c[1] for c in chunk_meta]
    conn.close()

    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        emb_meta = json.load(f)

    embeddings_sha = sha256_file(EMBEDDINGS_BIN)
    recorded_embeddings_sha = emb_meta.get("sha256", "")
    if recorded_embeddings_sha and recorded_embeddings_sha != embeddings_sha:
        print(
            f"ERROR: embeddings_meta.json sha256 ({recorded_embeddings_sha}) "
            f"does not match {EMBEDDINGS_BIN} ({embeddings_sha}).",
            file=sys.stderr,
        )
        sys.exit(1)

    emb_mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(
        emb_meta["rows"], emb_meta["dim"]
    )

    in_scope, out_of_scope = load_question_sets()

    target_by_id = {}
    alts_by_id = {}
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                if obj.get("in_scope"):
                    target_by_id[obj["id"]] = obj.get("target_chunk_id")
                    alts_by_id[obj["id"]] = obj.get("alt_chunk_ids", [])

    all_qs = list(in_scope) + list(out_of_scope)
    q_texts = [q["q"] for q in all_qs]
    q_vecs = embed_texts(q_texts, kind="query")

    fieldnames = [
        "group", "cls", "id", "question",
        "rank_1_chunk_id", "rank_1_page", "rank_1_dense_cosine",
        "rank_2_chunk_id", "rank_2_page", "rank_2_dense_cosine",
        "rank_3_chunk_id", "rank_3_page", "rank_3_dense_cosine",
        "rank_4_chunk_id", "rank_4_page", "rank_4_dense_cosine",
        "rank_5_chunk_id", "rank_5_page", "rank_5_dense_cosine",
        "target_chunk_id", "alt_chunk_ids",
    ]

    rows = []
    for idx, q in enumerate(all_qs):
        group = "in" if idx < len(in_scope) else "out"
        cls_val = "IN" if group == "in" else q.get("cls", "OOS")
        qid = q["id"]
        qtext = q["q"]
        q_vec = q_vecs[idx]

        scores = emb_mat @ q_vec
        top5_idx = np.argsort(-scores)[:5]

        target_chunk = target_by_id.get(qid, "") if group == "in" else ""
        alts = alts_by_id.get(qid, []) if group == "in" else []
        alt_str = ",".join(map(str, alts)) if alts else ""

        row = {
            "group": group,
            "cls": cls_val,
            "id": qid,
            "question": qtext,
            "target_chunk_id": target_chunk,
            "alt_chunk_ids": alt_str,
        }
        for r in range(1, 6):
            c_i = top5_idx[r - 1]
            row[f"rank_{r}_chunk_id"] = chunk_ids[c_i]
            row[f"rank_{r}_page"] = chunk_pages[c_i]
            row[f"rank_{r}_dense_cosine"] = f"{float(scores[c_i]):.6f}"
        rows.append(row)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    csv_sha = sha256_file(OUT_CSV)

    reference_meta = {
        "reference_version": 1,
        "generated_by": "scripts/export_retrieval_top5.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "retrieval_top5_csv": OUT_CSV,
        "retrieval_top5_csv_sha256": csv_sha,
        "rows": len(rows),
        "embeddings_bin": EMBEDDINGS_BIN,
        "embeddings_bin_sha256": embeddings_sha,
        "embeddings_meta_sha256": sha256_file(EMBEDDINGS_META),
        "embeddings_rows": emb_meta["rows"],
        "embeddings_dim": emb_meta["dim"],
        "cpu_model": cpu_model(),
        "onnxruntime_version": ort.__version__,
        "python_version": platform.python_version(),
    }
    with open(OUT_META, "w", encoding="utf-8") as f:
        json.dump(reference_meta, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"embeddings.bin sha256: {embeddings_sha}")
    print(f"CPU model: {reference_meta['cpu_model']}")
    print(f"onnxruntime version: {reference_meta['onnxruntime_version']}")
    print(f"Wrote {OUT_CSV} with {len(rows)} rows. SHA256: {csv_sha}")
    print(f"Wrote {OUT_META}")


if __name__ == "__main__":
    main()
