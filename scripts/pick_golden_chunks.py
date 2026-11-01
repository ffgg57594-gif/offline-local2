#!/usr/bin/env python3
"""Pick 60 golden chunks from books_knowledge.db for golden v3 question authoring.

Selects 60 in-scope chunks with fixed seed (7), stratified over the whole book
(one from every consecutive block of ~19 chunks), excluding chunks under 60
words and chunks that are mostly lists of numbers or figure captions.

Writes the FULL text of each selected chunk (id, page, text) to
eval/chunks_for_golden.jsonl and prints every chunk in full between clear
markers so a human can author questions from the real chunk text in PASS 2.

Output: eval/chunks_for_golden.jsonl
"""
import json
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
OUT_PATH = os.path.join("eval", "chunks_for_golden.jsonl")
SEED = 7
N_CHUNKS = 60
MIN_WORDS = 60


def is_figure_caption(text):
    """True if the chunk looks like a figure caption (starts with 'Fig' or 'Figure')."""
    return bool(re.match(r"^(Fig|Figure|TABLE|Table)\s*\d", text.strip()))


def is_number_list(text):
    """True if the chunk is mostly numbers/symbols (letter ratio < 0.6)."""
    letters = sum(1 for c in text if c.isalpha())
    non_space = sum(1 for c in text if not c.isspace())
    if non_space == 0:
        return True
    return letters / non_space < 0.6


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run build_knowledge_db.py first.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get all chunks ordered by id, with word_count >= MIN_WORDS.
    rows = cur.execute(
        "SELECT c.id, c.page, c.text, c.word_count "
        "FROM chunks c "
        "WHERE c.word_count >= ? ORDER BY c.id",
        (MIN_WORDS,),
    ).fetchall()

    # Filter out figure captions and number lists.
    eligible = []
    for cid, page, text, wc in rows:
        if is_figure_caption(text):
            continue
        if is_number_list(text):
            continue
        eligible.append((cid, page, text, wc))

    print(f"Total chunks with word_count >= {MIN_WORDS}: {len(rows)}")
    print(f"Eligible chunks (not caption/list): {len(eligible)}")

    if len(eligible) < N_CHUNKS:
        print(f"ERROR: Only {len(eligible)} eligible chunks, need {N_CHUNKS}.", file=sys.stderr)
        sys.exit(1)

    # Stratified selection: one chunk from every consecutive block of ~19 chunks.
    block_size = len(eligible) // N_CHUNKS
    import random
    rng = random.Random(SEED)
    selected = []
    for i in range(N_CHUNKS):
        start = i * block_size
        end = min((i + 1) * block_size, len(eligible))
        block = eligible[start:end]
        chosen = rng.choice(block)
        selected.append(chosen)

    # Sort by chunk id for deterministic output.
    selected.sort(key=lambda x: x[0])

    # Write full chunk text to JSONL.
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for cid, page, text, wc in selected:
            line = json.dumps({
                "id": cid,
                "page": page,
                "text": text,
                "word_count": wc,
            }, ensure_ascii=False)
            f.write(line + "\n")

    print(f"Wrote {OUT_PATH} with {len(selected)} chunks (seed={SEED}, block_size~{block_size})")

    # Print every chunk in full between clear markers for CI log review.
    print("\n" + "=" * 70)
    print("=== PICKED GOLDEN CHUNKS (full text, seed=%d) ===" % SEED)
    print("=" * 70)
    for idx, (cid, page, text, wc) in enumerate(selected, start=1):
        print(f"\n--- Chunk {idx}/{N_CHUNKS}: id={cid} page={page} words={wc} ---")
        print(text)
    print("=" * 70)
    print("=== END OF PICKED GOLDEN CHUNKS ===")
    print("=" * 70 + "\n")

    conn.close()


if __name__ == "__main__":
    main()
