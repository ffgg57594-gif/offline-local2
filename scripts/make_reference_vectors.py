#!/usr/bin/env python3
"""Create embedder_reference.json: 24 reference texts with tokens + vectors.

24 entries:
  - 12 English medical sentences from real chunks (seed 7), kind=passage
  - 6 Arabic medical questions, kind=query
  - 3 mixed Arabic/English, kind=query
  - 3 edge cases (very short, digits/symbols, >384 tokens), kind=query

For each entry: id, kind, input, tokens (token id list), vector (384 floats).
This file is the ground truth for Kotlin parity tests in a later stage.
"""
import hashlib
import json
import os
import random
import sqlite3
import sys

import numpy as np

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
OUT_PATH = os.path.join("app", "src", "main", "assets", "embedder_reference.json")

EMBED_DIM = 384
MAX_LENGTH = 384
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts, _load, _tokenize_batch  # noqa: E402

ARABIC_QUESTIONS = [
    "ما هي أسباب تسمم الحمل وكيفية علاجه؟",
    "ما هي أسباب الولادة المبكرة وكيفية الوقاية منها؟",
    "كيف يتم علاج النزيف بعد الولادة؟",
    "ما هي أعراض سكر الحمل ومضاعفاته على الجنين؟",
    "ما هي أسباب العقم عند الرجال والنساء؟",
    "كيف يتم تشخيص وعلاج فقر الدم الشديد؟",
]

MIXED_QUESTIONS = [
    "혈압 monitoring for preeclampsia and gestational hypertension treatment",
    "ما هو治疗 plan for postpartum hemorrhage with uterine atony?",
    "screening لـ gestational diabetes mellitus في الحمل عالي الخطورة",
]

EDGE_CASES = [
    "حمى",  # very short
    "BP 120/80 mmHg, Hb 12.5 g/dL, Plt 150,000 /µL, glucose 100 mg/dL",  # digits + symbols
    # Text longer than 384 tokens (repetitive medical text)
    ("preterm labor preterm labor preterm labor " * 200),  # ~1400 words, will be truncated
]


def _pick_english_sentences(seed: int, count: int = 12):
    """Pick `count` English sentences from real chunks, using fixed seed."""
    rng = random.Random(seed)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    # Pick random chunk ids.
    ids = rng.sample(range(1, total + 1), min(count, total))
    sentences = []
    for cid in ids:
        row = cur.execute("SELECT text FROM chunks WHERE id = ?", (cid,)).fetchone()[0]
        conn2 = sqlite3.connect(DB_PATH)
        cur2 = conn2.cursor()
        # Split into sentences and pick one.
        parts = [p.strip() for p in __import__("re").split(r"(?<=[.!?])\s+", row) if len(p.strip()) > 20]
        conn2.close()
        if parts:
            sentences.append(rng.choice(parts))
        else:
            sentences.append(row[:200])
    conn.close()
    return sentences


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run build_knowledge_db.py first.", file=sys.stderr)
        sys.exit(1)

    # Ensure model is loaded.
    _load()

    entries = []
    entry_id = 1

    # 1. 12 English medical sentences from real chunks (seed 7).
    english_sentences = _pick_english_sentences(7, 12)
    for s in english_sentences:
        vectors = embed_texts([s], kind="passage")
        session, tokenizer = _load()
        enc = tokenizer.encode(PASSAGE_PREFIX + s)
        tokens = enc.ids[:MAX_LENGTH]
        entries.append({
            "id": entry_id,
            "kind": "passage",
            "source": "real_chunk_english",
            "input": s,
            "tokens": tokens,
            "vector": vectors[0].tolist(),
        })
        entry_id += 1

    # 2. 6 Arabic medical questions.
    for q in ARABIC_QUESTIONS:
        vectors = embed_texts([q], kind="query")
        session, tokenizer = _load()
        enc = tokenizer.encode(QUERY_PREFIX + q)
        tokens = enc.ids[:MAX_LENGTH]
        entries.append({
            "id": entry_id,
            "kind": "query",
            "source": "arabic_medical_question",
            "input": q,
            "tokens": tokens,
            "vector": vectors[0].tolist(),
        })
        entry_id += 1

    # 3. 3 mixed Arabic/English.
    for q in MIXED_QUESTIONS:
        vectors = embed_texts([q], kind="query")
        session, tokenizer = _load()
        enc = tokenizer.encode(QUERY_PREFIX + q)
        tokens = enc.ids[:MAX_LENGTH]
        entries.append({
            "id": entry_id,
            "kind": "query",
            "source": "mixed_arabic_english",
            "input": q,
            "tokens": tokens,
            "vector": vectors[0].tolist(),
        })
        entry_id += 1

    # 4. 3 edge cases.
    for q in EDGE_CASES:
        vectors = embed_texts([q], kind="query")
        session, tokenizer = _load()
        enc = tokenizer.encode(QUERY_PREFIX + q)
        tokens = enc.ids[:MAX_LENGTH]
        entries.append({
            "id": entry_id,
            "kind": "query",
            "source": "edge_case",
            "input": q,
            "tokens": tokens,
            "vector": vectors[0].tolist(),
        })
        entry_id += 1

    assert len(entries) == 24, f"Expected 24 entries, got {len(entries)}"

    # Compute sha256 of the JSON content for integrity.
    json_bytes = json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8")
    digest = hashlib.sha256(json_bytes).hexdigest()

    output = {
        "dim": EMBED_DIM,
        "count": len(entries),
        "model": "multilingual-e5-small-quantized",
        "sha256": digest,
        "entries": entries,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {OUT_PATH}: {len(entries)} entries, sha256={digest}")
    print("Reference vectors complete.")


if __name__ == "__main__":
    main()
