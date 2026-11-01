#!/usr/bin/env python3
"""Failure review: list every in-scope question that misses at top-5 under the chosen fusion.

Supports two golden formats:
  - golden_v2.draft.jsonl: page-level labels (expected_pages, answer_terms) -> "before label fixes"
  - golden_v3.draft.jsonl: chunk-level labels (target_chunk_id, alt_chunk_ids) -> "after label fixes"

For each failure: id, question, top-3 pages with a 250-character snippet centred on the
sentence with the most query-word overlap. Marks which failures look like label problems
vs real retrieval misses with a one-line reason.

Usage: python scripts/failure_review.py [golden_path]
       Defaults to eval/golden_v3.draft.jsonl
"""
import json
import os
import re
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts  # noqa: E402
from keyword_builder import build_keyword_query, fts_search, load_stopwords, load_variant_map  # noqa: E402
from fusion_tuning import weighted_rrf, dense_search  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
DEFAULT_GOLDEN_PATH = os.path.join("eval", "golden_v3.draft.jsonl")

EMBED_DIM = 384


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat


def centre_snippet(text, query, window=250):
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
        best_sent = text[:window]
    snippet = best_sent.strip()
    if len(snippet) > window:
        snippet = snippet[:window]
    return snippet


def is_golden_v3(q):
    """Detect golden_v3 format by presence of target_chunk_id."""
    return "target_chunk_id" in q and q["target_chunk_id"] is not None


def main():
    golden_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOLDEN_PATH
    label = "after label fixes (chunk-level)" if golden_path.endswith("golden_v3.draft.jsonl") else "before label fixes (page-level)"

    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(EMBEDDINGS_BIN):
        print(f"ERROR: {EMBEDDINGS_BIN} not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(golden_path):
        print(f"ERROR: {golden_path} not found.", file=sys.stderr)
        sys.exit(1)

    embeddings = load_embeddings()

    with open(golden_path, "r", encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]
    questions = [q for q in questions if q.get("in_scope", False)]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    id_to_index = {cid: i for i, (cid, _, _, _) in enumerate(chunk_meta)}

    stopwords = set()
    variant_map = {}

    lines = [f"# Failure Review ({label})", "",
             "| ID | Question | Expected | Top-3 pages | Snippet | Assessment |",
             "|---|---|---|---|---|---|"]

    failures = 0
    # Build text lookup from chunk_meta: cid -> text
    text_lookup = {row[0]: row[3] for row in chunk_meta}
    for q in questions:
        query_text = q["q"]

        q_vec = embed_texts([query_text], kind="query")[0]
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=5)

        kw_query, _ = build_keyword_query(query_text, stopwords, set(), variant_map, variant="v2")
        kw_res = fts_search(cur, kw_query, top_k=5) if kw_query else []

        fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=0.5, k=60, top_k=5)

        hit = False
        expected_str = ""
        if is_golden_v3(q):
            target_id = q["target_chunk_id"]
            alt_ids = q.get("alt_chunk_ids") or []
            valid_ids = {target_id} | set(alt_ids)
            expected_str = f"chunk {target_id}" + (f" + alts {alt_ids}" if alt_ids else "")
            hit = any(r[0] in valid_ids for r in fused[:5])
        else:
            expected = set(q.get("expected_pages", []))
            expected_str = ", ".join(map(str, sorted(expected))) if expected else "-"
            hit = any(r[2] in expected for r in fused[:5])

        if hit:
            continue

        failures += 1
        top3_pages = [r[2] for r in fused[:3]]
        snippets = [centre_snippet(text_lookup.get(r[0], ""), query_text, 250) for r in fused[:3]]

        # Assessment: label problem vs real miss.
        dense_pages = [r[2] for r in dense_res[:5]]
        dense_ids = [r[0] for r in dense_res[:5]]
        if is_golden_v3(q):
            if target_id in dense_ids or any(aid in dense_ids for aid in alt_ids):
                assessment = "Label/fusion issue: expected chunk in dense top-5 but not fusion top-5"
            else:
                assessment = "Real retrieval miss: expected chunk not in dense top-5"
        else:
            if any(p in expected for p in dense_pages):
                assessment = "Label/fusion issue: expected page in dense top-5 but not fusion top-5"
            else:
                assessment = "Real retrieval miss: expected page not in dense top-5"

        snippet_str = " | ".join(s[:80] for s in snippets)
        lines.append(f"| {q['id']} | {q['q']} | {expected_str} | {top3_pages} | {snippet_str} | {assessment} |")

    lines.append("")
    lines.append(f"Total failures at top-5: {failures} of {len(questions)}")

    print("\n".join(lines))

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    conn.close()
    print("Failure review complete.")


if __name__ == "__main__":
    main()
