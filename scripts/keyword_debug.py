#!/usr/bin/env python3
"""Keyword debug step for CI.

Prints FTS integrity info, CREATE statements, MATCH counts, and tests
8 hand-written questions through the production keyword builder + FTS search.
This step is informational only and does not fail CI.
"""
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keyword_builder import build_keyword_query, fts_search, load_stopwords, load_variant_map  # noqa: E402

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
NORMALIZE_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")

# 8 hand-written questions spanning the book.
DEBUG_QUESTIONS = [
    "What is preeclampsia?",
    "What is placenta previa?",
    "What is placental abruption?",
    "What is fetal presentation?",
    "What is gestational diabetes?",
    "What is postpartum hemorrhage?",
    "What is preterm labour?",
    "What is ectopic pregnancy?",
]


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # --- FTS integrity ---
    print("=== Keyword Debug: FTS Integrity ===")
    chunks_count = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    fts_count = cur.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    print(f"chunks table rows: {chunks_count}")
    print(f"chunks_fts table rows: {fts_count}")

    # Integrity check.
    try:
        cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('integrity-check')")
        print("FTS integrity-check: OK")
    except Exception as e:
        print(f"FTS integrity-check FAILED: {e}", file=sys.stderr)

    # CREATE statements.
    print("\n=== CREATE statements ===")
    for row in cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name IN ('chunks', 'chunks_fts', 'books', 'meta') ORDER BY name"
    ):
        print(row[0])
        print()

    # MATCH counts for key terms.
    print("=== MATCH counts for key terms ===")
    for term in ["fetal", "preeclampsia", "hemorrhage", "placenta previa", "abruption"]:
        try:
            cnt = cur.execute(
                "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (term,)
            ).fetchone()[0]
            print(f'MATCH "{term}": {cnt} rows')
        except Exception as e:
            print(f'MATCH "{term}" ERROR: {e}')

    # --- Keyword builder + FTS search for 8 questions ---
    stopwords = load_stopwords()
    variant_map = (
        load_variant_map(NORMALIZE_MAP_PATH) if os.path.exists(NORMALIZE_MAP_PATH) else {}
    )
    print(f"\nStopwords count: {len(stopwords)}")
    print(f"Variant map entries: {len(variant_map)}")

    print("\n=== 8 Question Debug Rows ===")
    print(
        "| # | Question | Normalized tokens | FTS query string | Direct MATCH count | Top-3 chunk ids (bm25) |"
    )
    print("|---|---|---|---|---|---|")

    for i, q in enumerate(DEBUG_QUESTIONS, 1):
        # Normalize tokens (same as builder).
        from text_normalize import normalize_text  # noqa: E402

        norm = normalize_text(q, variant_map)
        tokens = re.findall(r"\w+", norm.lower())

        # Build FTS query (v2 = stopword-only unigrams with OR).
        kw_query, content_tokens = build_keyword_query(
            q, stopwords, set(), variant_map, variant="v2"
        )

        # Direct MATCH count.
        match_count = 0
        top3 = []
        if kw_query:
            try:
                match_count = cur.execute(
                    "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
                    (kw_query,),
                ).fetchone()[0]
                rows = fts_search(cur, kw_query, top_k=3)
                top3 = [(r[0], r[2], round(r[4], 2)) for r in rows]
            except Exception as e:
                match_count = f"ERROR: {e}"

        print(
            f"| {i} | {q} | {content_tokens} | {kw_query} | {match_count} | {top3} |"
        )

    conn.close()
    print("\nKeyword debug complete.")


if __name__ == "__main__":
    main()
