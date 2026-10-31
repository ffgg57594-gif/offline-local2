#!/usr/bin/env python3
"""Evaluation audit for Stage 3.6b.

Defines two hit concepts explicitly:
  - Answer-term hit: a chunk is a HIT if it contains ALL terms of at least one
    answer_terms group (checked with the same normalization and tokenizer as
    the index). A result list is a hit at k if any of its top-k chunks is a HIT.
  - Page hit: a result list is a page hit at k if any of its top-k chunks has
    a page number in expected_pages.

For every in-scope question prints one row:
  id | question | num chunks matching answer_terms | first 8 matching pages | expected_pages |
  rank of first answer-term hit in dense top-10 (or "none") | rank of first page hit | top-3 pages

Flags "weak label" questions: answer_terms matching more than 15 chunks.
Reports recall for all questions and for strong-label questions only (<= 15 matching chunks).
Writes all 60 rows to $GITHUB_STEP_SUMMARY.
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
from keyword_builder import (
    build_keyword_query,
    load_stopwords,
    load_variant_map,
    answer_terms_match,
    answer_terms_match_fts,
)  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_PATH = os.path.join("eval", "golden_v2.draft.jsonl")
NORMALIZE_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")

EMBED_DIM = 384
WEAK_LABEL_THRESHOLD = 15  # > 15 matching chunks => weak label


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat, meta


def load_golden():
    questions = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return [q for q in questions if q["in_scope"] and q["lang"] == "en"]


def dense_search(query_vec, embeddings, chunk_meta, top_k=10):
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((cid, name, page, text, float(scores[idx])))
    return results


def compute_chunk_match_counts(cur, questions, variant_map):
    """For each question, count how many chunks match answer_terms via FTS5."""
    match_counts = {}
    match_pages = {}
    for q in questions:
        qid = q["id"]
        terms = q.get("answer_terms") or []
        matching_chunks = []
        matching_pages = []
        if terms:
            # Get all chunk ids and texts.
            cur.execute("SELECT c.id, c.page, c.search_text FROM chunks c ORDER BY c.id")
            for cid, page, search_text in cur.fetchall():
                if answer_terms_match(search_text, terms, variant_map):
                    matching_chunks.append(cid)
                    matching_pages.append(page)
        match_counts[qid] = len(matching_chunks)
        match_pages[qid] = matching_pages
    return match_counts, match_pages


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


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
    chunk_sha256 = meta.get("chunk_texts_sha256", "unknown")
    bin_sha256 = sha256_file(EMBEDDINGS_BIN)
    print(f"embeddings.bin sha256: {bin_sha256}")
    print(f"chunk_texts_sha256 (from meta): {chunk_sha256}")
    print(f"embeddings rows: {meta.get('rows', 'unknown')}, dim: {meta.get('dim', 'unknown')}")

    questions = load_golden()
    print(f"In-scope English questions: {len(questions)}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    id_to_index = {cid: i for i, (cid, _, _, _) in enumerate(chunk_meta)}

    variant_map = load_variant_map(NORMALIZE_MAP_PATH) if os.path.exists(NORMALIZE_MAP_PATH) else {}
    stopwords = load_stopwords()

    # Compute answer-term match counts for all questions.
    match_counts, match_pages = compute_chunk_match_counts(cur, questions, variant_map)

    # Classify weak vs strong labels.
    weak_label_qids = set()
    strong_label_qids = set()
    for q in questions:
        qid = q["id"]
        if match_counts[qid] > WEAK_LABEL_THRESHOLD:
            weak_label_qids.add(qid)
        else:
            strong_label_qids.add(qid)

    print(f"\nWeak label (>15 matching chunks): {len(weak_label_qids)} questions")
    print(f"Strong label (<=15 matching chunks): {len(strong_label_qids)} questions")

    # Evaluate dense search under both definitions.
    def dense_hit_at_k(results, expected_pages, match_counts, qid, k):
        """Answer-term hit: any top-k chunk matches answer_terms."""
        for rank, (cid, _name, page, _text, _score) in enumerate(results[:k], start=1):
            if cid in match_counts and match_counts[cid] > 0:
                # Need to check if this specific chunk matches, not just the question.
                # Re-check: does this specific chunk match the question's answer_terms?
                q = next(qq for qq in questions if qq["id"] == qid)
                terms = q.get("answer_terms") or []
                # Get the chunk's search_text.
                cur.execute("SELECT search_text FROM chunks WHERE id = ?", (cid,))
                row = cur.fetchone()
                if row and answer_terms_match(row[0], terms, variant_map):
                    return rank
        return None

    def page_hit_at_k(results, expected_pages, k):
        for rank, (_cid, _name, page, _text, _score) in enumerate(results[:k], start=1):
            if page in expected_pages:
                return rank
        return None

    # Build result rows for all questions.
    rows = []
    for q in questions:
        qid = q["id"]
        query_text = q["q"]
        expected_pages = set(q["expected_pages"])
        terms = q.get("answer_terms") or []

        q_vec = embed_texts([query_text], kind="query")[0]
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=10)

        ans_rank = dense_hit_at_k(dense_res, expected_pages, match_counts, qid, 10)
        page_rank = page_hit_at_k(dense_res, expected_pages, 10)

        top3_pages = [r[2] for r in dense_res[:3]]
        matching_page_list = match_pages.get(qid, [])
        first8_pages = matching_page_list[:8]

        rows.append({
            "id": qid,
            "question": query_text,
            "num_matching_chunks": match_counts[qid],
            "first_8_matching_pages": first8_pages,
            "expected_pages": sorted(expected_pages),
            "ans_term_rank": ans_rank,
            "page_rank": page_rank,
            "top3_pages": top3_pages,
            "is_weak": qid in weak_label_qids,
        })

    # Print audit table to stdout (summary) and full to GITHUB_STEP_SUMMARY.
    summary_lines = ["# Evaluation Audit: Hit Definition Analysis", ""]
    summary_lines.append("## Hit Definitions", "")
    summary_lines.append("- **Answer-term hit**: chunk contains ALL terms of at least one answer_terms group.")
    summary_lines.append("- **Page hit**: chunk page number is in expected_pages.")
    summary_lines.append("- **Weak label**: answer_terms matches more than 15 chunks.")
    summary_lines.append("")
    summary_lines.append(f"## Chunk-Text SHA256 Check", "")
    summary_lines.append(f"- embeddings.bin sha256: `{bin_sha256}`")
    summary_lines.append(f"- chunk_texts_sha256 from meta: `{chunk_sha256}`")
    summary_lines.append("")
    summary_lines.append("## Weak Label Questions (>15 matching chunks)", "")
    weak_list = sorted(weak_label_qids)
    if weak_list:
        summary_lines.append(f"Question IDs: {weak_list}")
    else:
        summary_lines.append("None")
    summary_lines.append("")
    summary_lines.append("## Full Audit Table (all 60 in-scope questions)", "")
    summary_lines.append("| id | question | num_matching_chunks | first_8_matching_pages | expected_pages | ans_term_rank | page_rank | top3_pages | weak_label |")
    summary_lines.append("|---|---|---|---|---|---|---|---|---|")

    for r in rows:
        summary_lines.append(
            f"| {r['id']} | {r['question']} | {r['num_matching_chunks']} | "
            f"{r['first_8_matching_pages']} | {r['expected_pages']} | "
            f"{r['ans_term_rank'] if r['ans_term_rank'] is not None else 'none'} | "
            f"{r['page_rank'] if r['page_rank'] is not None else 'none'} | "
            f"{r['top3_pages']} | {r['is_weak']} |"
        )

    # Compute recall under both definitions.
    def recall_at_k_def(rows_list, rank_field, k):
        hits = 0
        for r in rows_list:
            rank = r[rank_field]
            if rank is not None and rank <= k:
                hits += 1
        return hits / len(rows_list)

    def mrr_def(rows_list, rank_field):
        ranks = [r[rank_field] for r in rows_list if r[rank_field] is not None]
        if not ranks:
            return 0.0
        return sum(1.0 / r for r in ranks) / len(rows_list)

    all_recall = {
        "ans_term": {
            "hit1": recall_at_k_def(rows, "ans_term_rank", 1),
            "hit3": recall_at_k_def(rows, "ans_term_rank", 3),
            "hit5": recall_at_k_def(rows, "ans_term_rank", 5),
            "mrr": mrr_def(rows, "ans_term_rank"),
        },
        "page": {
            "hit1": recall_at_k_def(rows, "page_rank", 1),
            "hit3": recall_at_k_def(rows, "page_rank", 3),
            "hit5": recall_at_k_def(rows, "page_rank", 5),
            "mrr": mrr_def(rows, "page_rank"),
        },
    }

    # Strong label only recall.
    strong_rows = [r for r in rows if not r["is_weak"]]
    strong_recall = {
        "ans_term": {
            "hit1": recall_at_k_def(strong_rows, "ans_term_rank", 1),
            "hit3": recall_at_k_def(strong_rows, "ans_term_rank", 3),
            "hit5": recall_at_k_def(strong_rows, "ans_term_rank", 5),
            "mrr": mrr_def(strong_rows, "ans_term_rank"),
        },
        "page": {
            "hit1": recall_at_k_def(strong_rows, "page_rank", 1),
            "hit3": recall_at_k_def(strong_rows, "page_rank", 3),
            "hit5": recall_at_k_def(strong_rows, "page_rank", 5),
            "mrr": mrr_def(strong_rows, "page_rank"),
        },
    }

    # Disagreement rows: where the two definitions disagree or no hit in top-5.
    disagreement = []
    no_hit_top5 = []
    for r in rows:
        ans_in_top5 = r["ans_term_rank"] is not None and r["ans_term_rank"] <= 5
        page_in_top5 = r["page_rank"] is not None and r["page_rank"] <= 5
        if ans_in_top5 != page_in_top5:
            disagreement.append(r)
        if not ans_in_top5 and not page_in_top5:
            no_hit_top5.append(r)

    summary_lines.append("")
    summary_lines.append("## Disagreement Rows (definitions differ or no hit in top-5)", "")
    summary_lines.append(f"- Rows where definitions disagree: {len(disagreement)}")
    summary_lines.append(f"- Rows with no hit in top-5 under either definition: {len(no_hit_top5)}")
    summary_lines.append("")
    if disagreement:
        summary_lines.append("### Disagreement details")
        summary_lines.append("| id | question | ans_term_rank | page_rank | top3_pages | expected_pages |")
        summary_lines.append("|---|---|---|---|---|---|")
        for r in disagreement:
            summary_lines.append(
                f"| {r['id']} | {r['question']} | {r['ans_term_rank'] if r['ans_term_rank'] is not None else 'none'} | "
                f"{r['page_rank'] if r['page_rank'] is not None else 'none'} | {r['top3_pages']} | {r['expected_pages']} |"
            )
    summary_lines.append("")
    if no_hit_top5:
        summary_lines.append("### No hit in top-5 (both definitions)")
        summary_lines.append("| id | question | top3_pages | expected_pages |")
        summary_lines.append("|---|---|---|---|")
        for r in no_hit_top5:
            summary_lines.append(f"| {r['id']} | {r['question']} | {r['top3_pages']} | {r['expected_pages']} |")

    # Print recall tables.
    summary_lines.append("")
    summary_lines.append("## Dense Recall: All Questions (60)", "")
    summary_lines.append("| Definition | Hit@1 | Hit@3 | Hit@5 | MRR |")
    summary_lines.append("|---|---|---|---|---|")
    for def_name in ["ans_term", "page"]:
        r = all_recall[def_name]
        summary_lines.append(f"| {def_name} | {r['hit1']:.3f} | {r['hit3']:.3f} | {r['hit5']:.3f} | {r['mrr']:.3f} |")

    summary_lines.append("")
    summary_lines.append("## Dense Recall: Strong Label Only (<=15 matching chunks)", "")
    summary_lines.append(f"Number of strong-label questions: {len(strong_rows)}")
    summary_lines.append("")
    summary_lines.append("| Definition | Hit@1 | Hit@3 | Hit@5 | MRR |")
    summary_lines.append("|---|---|---|---|---|")
    for def_name in ["ans_term", "page"]:
        r = strong_recall[def_name]
        summary_lines.append(f"| {def_name} | {r['hit1']:.3f} | {r['hit3']:.3f} | {r['hit5']:.3f} | {r['mrr']:.3f} |")

    # Print to stdout.
    print("\n".join(summary_lines[:15]))
    print(f"\nWeak label count: {len(weak_label_qids)}")
    print(f"Strong label count: {len(strong_label_qids)}")
    print(f"\nRecall - All questions:")
    for def_name in ["ans_term", "page"]:
        r = all_recall[def_name]
        print(f"  {def_name}: Hit@1={r['hit1']:.3f} Hit@3={r['hit3']:.3f} Hit@5={r['hit5']:.3f} MRR={r['mrr']:.3f}")
    print(f"\nRecall - Strong label only:")
    for def_name in ["ans_term", "page"]:
        r = strong_recall[def_name]
        print(f"  {def_name}: Hit@1={r['hit1']:.3f} Hit@3={r['hit3']:.3f} Hit@5={r['hit5']:.3f} MRR={r['mrr']:.3f}")
    print(f"\nDisagreement rows: {len(disagreement)}")
    print(f"No hit in top-5 rows: {len(no_hit_top5)}")

    # Write to GITHUB_STEP_SUMMARY.
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")

    # Print full golden question list.
    print("\n## Full Golden Question List (120 questions)", "")
    all_questions = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_questions.append(json.loads(line))
    for q in all_questions:
        terms_str = json.dumps(q.get("answer_terms") or q.get("key_terms") or [])
        print(f"{q['id']} | {q['lang']} | {q['q']} | {terms_str} | pages={q['expected_pages']}")

    conn.close()
    print("\nEvaluation audit complete.")


if __name__ == "__main__":
    main()
