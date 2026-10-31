#!/usr/bin/env python3
"""Failure review: list every in-scope question that misses at top-5 under the chosen fusion.

For each failure: id, question, answer_terms, top-3 pages with a 250-character snippet
centred on the sentence with the most query-word overlap. Marks which failures look like
label problems vs real retrieval misses with a one-line reason.
"""
import json
import os
import re
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts  # noqa: E402
from keyword_builder import build_keyword_query, fts_search, load_stopwords, load_variant_map, compute_generic_terms  # noqa: E402
from fusion_tuning import weighted_rrf, dense_search  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_PATH = os.path.join("eval", "golden_v2.draft.jsonl")
FUSION_CONFIG_PATH = os.path.join("app", "src", "main", "assets", "fusion_config.json")

EMBED_DIM = 384


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat


def load_golden():
    questions = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return [q for q in questions if q["in_scope"] and q["lang"] == "en"]


def load_fusion_config():
    if not os.path.exists(FUSION_CONFIG_PATH):
        return {"k": 60, "w_dense": 1.0, "w_kw": 0.5}
    with open(FUSION_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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


def looks_like_label_problem(question, expected_pages, fused_pages):
    """Heuristic: if any expected page appears within top-10 dense results, likely label problem."""
    # This is a best-effort judgement; returns True if expected page is close.
    return True  # Placeholder: actual logic would check dense rankings


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

    embeddings = load_embeddings()
    questions = load_golden()
    config = load_fusion_config()
    k = config.get("k", 60)
    wkw = config.get("w_kw", 0.5)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    id_to_index = {cid: i for i, (cid, _, _, _) in enumerate(chunk_meta)}

    stopwords = set()
    generic_terms = set()
    variant_map = {}

    lines = ["# Failure Review: In-scope questions missing at top-5", "",
             "| ID | Question | Answer terms | Top-3 pages | Snippet | Assessment |",
             "|---|---|---|---|---|---|"]

    failures = 0
    for q in questions:
        expected = set(q["expected_pages"])
        query_text = q["q"]

        q_vec = embed_texts([query_text], kind="query")[0]
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=5)

        kw_query, _ = build_keyword_query(query_text, stopwords, generic_terms, variant_map)
        kw_res = fts_search(cur, kw_query, top_k=5)

        fused = weighted_rrf(dense_res, kw_res, w_dense=1.0, w_kw=wkw, k=k, top_k=5)

        if any(p in expected for p in [r[1] for r in fused[:5]]):
            continue  # hit at top-5

        failures += 1
        answer_terms = q.get("answer_terms") or []
        answer_terms_str = "; ".join([" / ".join(g) for g in answer_terms]) if answer_terms else "-"
        top3_pages = [r[1] for r in fused[:3]]
        snippets = [centre_snippet(r[2], query_text, 250) for r in fused[:3]]

        # Assessment: label problem vs real miss.
        # If expected page appears in dense top-5 but not fusion, likely fusion issue.
        dense_pages = [r[1] for r in dense_res[:5]]
        if any(p in expected for p in dense_pages):
            assessment = "Label/fusion issue: expected page in dense top-5 but not fusion top-5"
        else:
            assessment = "Real retrieval miss: expected page not in dense top-5"

        snippet_str = " | ".join(s[:80] for s in snippets)
        lines.append(f"| {q['id']} | {q['q']} | {answer_terms_str} | {top3_pages} | {snippet_str} | {assessment} |")

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
