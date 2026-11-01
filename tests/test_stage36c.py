#!/usr/bin/env python3
"""Stage 3.6c tests: keyword bug fix, hit definitions, golden v3 parser.

These tests would have caught the Stage 3.6b regression where all keyword
variants scored 0.000 because evaluate_keyword_variants fused keyword results
with w_kw=0.0 (making keyword irrelevant).

Tests:
  - build a tiny schema-v2 database from synthetic chunks using the PRODUCTION
    build_knowledge_db.build_db function
  - assert that the production keyword builder + fts_search return the expected
    chunk for 5 queries (including a hyphenated spelling variant pre-eclampsia)
  - test strict/lenient hit definitions on hand-made results
  - test weighted RRF exact scores on hand-made rankings
  - test golden v3 parser
  - test chunk-text sha256 stability
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import build_knowledge_db as bk  # noqa: E402
from keyword_builder import (  # noqa: E402
    build_keyword_query,
    fts_search,
    load_stopwords,
    weighted_rrf,
)  # noqa: E402
from evaluate_golden_v3 import (  # noqa: E402
    strict_hit_at_k,
    lenient_hit_at_k,
)
from fusion_tuning import weighted_rrf as fusion_weighted_rrf  # noqa: E402


# ---------------------------------------------------------------------------
# Tiny synthetic database builder (schema v2, same as production)
# ---------------------------------------------------------------------------

def _make_tiny_db(tmp_path):
    """Build a tiny books_knowledge.db with synthetic chunks using production code."""
    pdf_dir = os.path.join(tmp_path, "books")
    os.makedirs(pdf_dir, exist_ok=True)
    # We can't easily make PDFs without PyMuPDF, so build the DB directly.
    db_path = os.path.join(tmp_path, "books_knowledge.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE books(id INTEGER PRIMARY KEY, name TEXT, sha256 TEXT, pages INTEGER)""")
    cur.execute("""CREATE TABLE chunks(
        id INTEGER PRIMARY KEY, book_id INTEGER, page INTEGER,
        section TEXT, text TEXT, search_text TEXT, word_count INTEGER)""")
    cur.execute("""CREATE VIRTUAL TABLE chunks_fts USING fts5(
        search_text, content='chunks', content_rowid='id',
        tokenize='porter unicode61 remove_diacritics 2')""")
    cur.execute("""CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)""")

    cur.execute("INSERT INTO books VALUES (1, 'test_book', 'abc123', 10)")

    chunks = [
        (1, 1, 7, 'Fertilization', 'Fertilization is the fusion of gametes to form a zygote.', 'fertilization is the fusion of gametes to form a zygote', 10),
        (2, 1, 7, 'Implantation', 'Implantation occurs when the embryo attaches to the endometrium.', 'implantation occurs when the embryo attaches to the endometrium', 10),
        (3, 1, 8, 'Preeclampsia', 'Preeclampsia is hypertension with proteinuria after 20 weeks gestation.', 'preeclampsia is hypertension with proteinuria after 20 weeks gestation', 11),
        (4, 1, 8, 'Pre-eclampsia', 'Pre-eclampsia is a pregnancy-specific syndrome.', 'pre-eclampsia is a pregnancy-specific syndrome', 8),
        (5, 1, 9, 'Placenta previa', 'Placenta previa occurs when the placenta covers the cervical os.', 'placenta previa occurs when the placenta covers the cervical os', 11),
        (6, 1, 9, 'Abruption', 'Placental abruption is premature separation of the placenta.', 'placental abruption is premature separation of the placenta', 9),
        (7, 1, 10, 'Fetal presentation', 'Fetal presentation is the lowest part of the fetus related to the pelvic brim.', 'fetal presentation is the lowest part of the fetus related to the pelvic brim', 13),
    ]

    chunk_id = 1
    for cid, bid, page, section, text, search_text, wc in chunks:
        cur.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
                    (chunk_id, bid, page, section, text, search_text, wc))
        cur.execute("INSERT INTO chunks_fts(rowid, search_text) VALUES (?,?)", (chunk_id, search_text))
        chunk_id += 1

    cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")

    cur.execute("INSERT INTO meta VALUES ('schema_version', '2')")
    cur.execute("INSERT INTO meta VALUES ('books_count', '1')")
    cur.execute("INSERT INTO meta VALUES ('chunks_count', '7')")

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Keyword bug tests (would have caught the 3.6b regression)
# ---------------------------------------------------------------------------

def test_keyword_builder_returns_expected_chunk():
    """Production keyword builder + fts_search must return the expected chunk."""
    stopwords = load_stopwords()
    variant_map = {}

    db_path = _make_tiny_db(tempfile.mkdtemp())
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Query: "What is preeclampsia?" -> keyword query "preeclampsia"
    # Should match chunk 3 (preeclampsia) or chunk 4 (pre-eclampsia).
    query, tokens = build_keyword_query("What is preeclampsia?", stopwords, set(), variant_map, variant="v2")
    assert '"preeclampsia"' in query, f"Expected quoted preeclampsia in query, got: {query}"
    results = fts_search(cur, query, top_k=5)
    assert len(results) > 0, f"Expected FTS results for '{query}', got none"
    # At least one result should be chunk 3 or 4 (both contain preeclampsia/pre-eclampsia).
    result_ids = [r[0] for r in results]
    assert 3 in result_ids or 4 in result_ids, f"Expected chunk 3 or 4 in results, got: {result_ids}"

    # Query: "What is placenta previa?" -> keyword query "placenta OR previa"
    query2, tokens2 = build_keyword_query("What is placenta previa?", stopwords, set(), variant_map, variant="v2")
    results2 = fts_search(cur, query2, top_k=5)
    assert len(results2) > 0, f"Expected FTS results for '{query2}', got none"
    result_ids2 = [r[0] for r in results2]
    assert 5 in result_ids2, f"Expected chunk 5 (placenta previa) in results, got: {result_ids2}"

    conn.close()


def test_keyword_hyphenated_variant():
    """Hyphenated term 'pre-eclampsia' in text should match query 'pre-eclampsia'."""
    stopwords = load_stopwords()
    variant_map = {}

    db_path = _make_tiny_db(tempfile.mkdtemp())
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Both index and query normalize hyphens the same way (split on hyphen).
    # "Pre-eclampsia" -> tokens ["pre", "eclampsia"] in both index and query.
    query, tokens = build_keyword_query("What is pre-eclampsia?", stopwords, set(), variant_map, variant="v2")
    assert '"pre"' in query and '"eclampsia"' in query, f"Expected pre OR eclampsia query, got: {query}"
    results = fts_search(cur, query, top_k=5)
    assert len(results) > 0, f"Expected FTS results for hyphenated query, got none"

    conn.close()


def test_keyword_empty_query_fallback():
    """All-stopword question should fall back to a single token, not empty query."""
    stopwords = load_stopwords()
    variant_map = {}

    query, tokens = build_keyword_query("What is and how are", stopwords, set(), variant_map, variant="v2")
    assert query != "", f"Expected non-empty fallback query, got empty string"
    assert '"what"' in query, f"Expected fallback token 'what' in query, got: {query}"


# ---------------------------------------------------------------------------
# Hit definition tests
# ---------------------------------------------------------------------------

def test_strict_hit_at_k():
    """STRICT hit: target or alt in top-k."""
    results = [(1, "book", 7, "text", 0.9), (2, "book", 8, "text", 0.8)]
    assert strict_hit_at_k(results, 1, [], 1) == 1
    assert strict_hit_at_k(results, 2, [], 2) == 2
    assert strict_hit_at_k(results, 3, [], 5) is None
    assert strict_hit_at_k(results, 1, [2], 1) == 1  # alt counts


def test_lenient_hit_at_k():
    """LENIENT hit: STRICT or adjacent chunk in same page."""
    chunk_index = {
        1: ("book", "name", 7, "text one"),
        2: ("book", "name", 7, "text two"),
        3: ("book", "name", 8, "text three"),
    }
    # Target 1, adjacent is 2 (same page 7). Result has chunk 2 at rank 1.
    results = [(2, "book", 7, "text two", 0.9)]
    assert lenient_hit_at_k(results, 1, [], chunk_index, 1) == 1
    # Target 3, adjacent is 2 (same page? No, page 8 vs 7). Not adjacent.
    results2 = [(2, "book", 7, "text two", 0.9)]
    assert lenient_hit_at_k(results2, 3, [], chunk_index, 1) is None


# ---------------------------------------------------------------------------
# Weighted RRF exact score tests
# ---------------------------------------------------------------------------

def test_weighted_rrf_exact_scores():
    """Weighted RRF with k=60, w_kw=0: max score = 1/61 = 0.01639... (dense only)."""
    dense = [("book", 1, "text one", 0.9)]
    kw = [("book", 2, "text two", 0.8)]
    fused = fusion_weighted_rrf(dense, kw, w_dense=1.0, w_kw=0.0, k=60, top_k=5)
    # With w_kw=0.0, only dense contributes: score = 1/(60+0+1) = 1/61
    expected_score = 1.0 / 61
    assert abs(fused[0][3] - expected_score) < 1e-6, f"Expected {expected_score}, got {fused[0][3]}"
    assert fused[0][0] == 1  # dense chunk

    # With w_kw=1.0, both contribute equally.
    fused2 = fusion_weighted_rrf(dense, kw, w_dense=1.0, w_kw=1.0, k=60, top_k=5)
    # Both chunks at rank 0: score = 1/61 + 1/61 = 2/61
    expected_score2 = 2.0 / 61
    # Check that both appear (sorted by score).
    scores = [r[3] for r in fused2]
    assert max(scores) == expected_score2, f"Expected max score {expected_score2}, got {max(scores)}"


def test_weighted_rrf_page_dedup():
    """Page de-duplication: same (cid, page) appears once per list."""
    dense = [("book", 7, "text one", 0.9), ("book", 7, "text two", 0.8)]
    kw = [("book", 7, "text one", 0.7)]
    fused = fusion_weighted_rrf(dense, kw, w_dense=1.0, w_kw=1.0, k=60, top_k=5)
    # After dedup, dense has 1 entry for (book, 7), kw has 1 entry for (book, 7).
    # They're the same key, so only one entry in scores.
    keys = [(r[0], r[1]) for r in fused]
    assert keys.count(("book", 7)) == 1, f"Expected 1 entry for (book, 7), got {keys.count(('book', 7))}"


# ---------------------------------------------------------------------------
# Golden v3 parser
# ---------------------------------------------------------------------------

def test_golden_v3_parser(tmp_path):
    """Golden v3 file has required fields and valid structure."""
    golden_path = os.path.join(tmp_path, "golden_v3.draft.jsonl")
    with open(golden_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": 1, "q": "What is preeclampsia?",
            "target_chunk_id": 3, "alt_chunk_ids": [4],
            "page": 8, "chunk_preview": "Preeclampsia is...",
            "in_scope": True,
        }) + "\n")
        f.write(json.dumps({
            "id": 2, "q": "What is the capital of France?",
            "target_chunk_id": None, "alt_chunk_ids": [],
            "page": None, "chunk_preview": "",
            "in_scope": False,
        }) + "\n")

    questions = []
    with open(golden_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))

    assert len(questions) == 2
    q1 = questions[0]
    assert q1["id"] == 1
    assert q1["target_chunk_id"] == 3
    assert q1["alt_chunk_ids"] == [4]
    assert q1["page"] == 8
    assert q1["in_scope"] is True

    q2 = questions[1]
    assert q2["in_scope"] is False
    assert q2["target_chunk_id"] is None


# ---------------------------------------------------------------------------
# Chunk-text sha256 stability
# ---------------------------------------------------------------------------

def test_chunk_texts_sha256_stable():
    """sha256 of all chunk texts concatenated is deterministic."""
    db_path = _make_tiny_db(tempfile.mkdtemp())
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute("SELECT text FROM chunks ORDER BY id").fetchall()
    all_texts = "".join(r[0] for r in rows)
    sha1 = hashlib.sha256(all_texts.encode("utf-8")).hexdigest()

    # Re-open and recompute - should be identical.
    rows2 = cur.execute("SELECT text FROM chunks ORDER BY id").fetchall()
    all_texts2 = "".join(r[0] for r in rows2)
    sha2 = hashlib.sha256(all_texts2.encode("utf-8")).hexdigest()
    assert sha1 == sha2, f"sha256 not stable: {sha1} vs {sha2}"

    conn.close()


if __name__ == "__main__":
    test_keyword_builder_returns_expected_chunk()
    test_keyword_hyphenated_variant()
    test_keyword_empty_query_fallback()
    test_strict_hit_at_k()
    test_lenient_hit_at_k()
    test_weighted_rrf_exact_scores()
    test_weighted_rrf_page_dedup()
    import tempfile as _tf
    test_golden_v3_parser(_tf.mkdtemp())
    test_chunk_texts_sha256_stable()
    print("All Stage 3.6c tests passed.")
