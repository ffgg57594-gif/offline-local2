#!/usr/bin/env python3
"""Print candidate alternate chunks for golden v3 questions.

For each question, computes dense top-5 and keyword top-5 (v2) and prints
candidate alternate chunks (id, page, 300-char snippet) that are NOT the
target chunk, so alt_chunk_ids can be decided by reading them.
"""
import hashlib
import json
import os
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

EMBED_DIM = 384


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat, meta


def dense_search(query_vec, embeddings, chunk_meta, top_k=5):
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((cid, name, page, text, float(scores[idx])))
    return results


def keyword_search(cur, query, stopwords, variant_map, top_k=5):
    kw_query, _ = build_keyword_query(query, stopwords, set(), variant_map, variant="v2")
    if not kw_query:
        return []
    return fts_search(cur, kw_query, top_k=top_k)


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
    print(f"embeddings.bin sha256: {bin_sha256}")
    print(f"embeddings rows: {meta.get('rows', 'unknown')}, dim: {meta.get('dim', 'unknown')}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()

    variant_map = load_variant_map(NORMALIZE_MAP_PATH) if os.path.exists(NORMALIZE_MAP_PATH) else {}
    stopwords = load_stopwords()

    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]
    questions = [q for q in questions if q.get("in_scope", False)]

    print(f"In-scope questions: {len(questions)}")
    print()

    # Embed all questions.
    query_texts = [q["q"] for q in questions]
    query_vecs = embed_texts(query_texts, kind="query")

    total_alternates = 0
    for qi, q in enumerate(questions):
        qid = q["id"]
        qtext = q["q"]
        target_id = q["target_chunk_id"]
        target_page = q.get("page", "?")

        q_vec = query_vecs[qi]

        # Dense top-5.
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=5)

        # Keyword top-5 (v2).
        kw_res = keyword_search(cur, qtext, stopwords, variant_map, top_k=5)

        # Collect candidate alternates (not target_id), preserving order.
        seen = {target_id}
        alternates = []
        for r in dense_res + kw_res:
            cid = r[0]
            if cid in seen:
                continue
            seen.add(cid)
            alternates.append(r)

        print(f"--- Q{qid}: {qtext} ---")
        print(f"Target: chunk {target_id} (page {target_page})")
        dense_ids = [r[0] for r in dense_res]
        kw_ids = [r[0] for r in kw_res]
        print(f"Dense top-5: {dense_ids}")
        print(f"Keyword top-5: {kw_ids}")
        if alternates:
            print("Candidate alternates:")
            for r in alternates[:8]:
                cid, name, page, text, score = r
                snip = snippet_centred(text, qtext, 300)
                print(f"  Chunk {cid} (page {page}): {snip}")
                total_alternates += 1
        else:
            print("  No candidate alternates found.")
        print()

    print(f"Total candidate alternates printed: {total_alternates}")

    conn.close()
    print("Candidate alternate chunks printed.")


if __name__ == "__main__":
    main()
