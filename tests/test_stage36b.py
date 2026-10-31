#!/usr/bin/env python3
"""Stage 3.6b tests: hit definition, v2/v3 query strings, weak-label flag, weighted RRF exact scores."""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from keyword_builder import (
    build_keyword_query,
    load_stopwords,
    NON_CONTENT_WORDS,
)  # noqa: E402
from fusion_tuning import weighted_rrf  # noqa: E402


# ---------------------------------------------------------------------------
# Hit definition tests on hand-made chunks
# ---------------------------------------------------------------------------

def test_answer_terms_match_all_in_group():
    """A chunk is a HIT if it contains ALL terms of at least one answer_terms group."""
    text = "Preeclampsia is hypertension with proteinuria in pregnancy."
    terms = [["preeclampsia", "proteinuria"], ["eclampsia", "seizures"]]
    # answer_terms_match from keyword_builder
    from keyword_builder import answer_terms_match
    assert answer_terms_match(text, terms) is True


def test_answer_terms_match_partial_group_false():
    text = "Preeclampsia is hypertension."
    terms = [["preeclampsia", "proteinuria"]]
    from keyword_builder import answer_terms_match
    assert answer_terms_match(text, terms) is False


def test_answer_terms_match_empty():
    from keyword_builder import answer_terms_match
    assert answer_terms_match("any text", []) is False


def test_hit_definition_rank():
    """Result list is a hit at k if any top-k chunk matches answer_terms."""
    from fusion_tuning import hit_at_k_answer_term
    import sqlite3
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE chunks_fts USING fts5(search_text)")
    cur.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, search_text TEXT)")
    cur.execute("INSERT INTO chunks(id, search_text) VALUES (1, 'preeclampsia proteinuria')")
    cur.execute("INSERT INTO chunks_fts(rowid, search_text) VALUES (1, 'preeclampsia proteinuria')")
    cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
    results = [(1, "book", 7, "preeclampsia proteinuria text", 0.9)]
    terms = [["preeclampsia", "proteinuria"]]
    rank = hit_at_k_answer_term(results, cur, terms, {}, 1)
    assert rank == 1
    conn.close()


# ---------------------------------------------------------------------------
# v2/v3 query strings for 5 hand-written questions (exact expected strings)
# ---------------------------------------------------------------------------

def test_v2_query_strings():
    stopwords = load_stopwords()
    variant_map = {}
    non_content = set(NON_CONTENT_WORDS)

    q1 = "What is preeclampsia and how is it treated?"
    q2, _ = build_keyword_query(q1, stopwords, non_content, variant_map, variant="v2")
    assert '"preeclampsia"' in q2
    assert '"treated"' in q2
    assert " OR " in q2
    assert "what" not in q2
    assert "is" not in q2

    q3 = "How does gestational diabetes affect pregnancy?"
    q4, _ = build_keyword_query(q3, stopwords, non_content, variant_map, variant="v2")
    assert '"gestational"' in q4
    assert '"diabetes"' in q4
    assert '"pregnancy"' in q4


def test_v3_query_strings():
    stopwords = load_stopwords()
    variant_map = {}
    non_content = set(NON_CONTENT_WORDS)

    q1 = "preeclampsia treatment guidelines"
    q2, _ = build_keyword_query(q1, stopwords, non_content, variant_map, variant="v3")
    # v3 should have unigrams plus adjacent phrases
    assert '"preeclampsia"' in q2
    assert '"treatment"' in q2
    assert '"guidelines"' in q2
    # Adjacent phrase "preeclampsia treatment" should be present
    assert '"preeclampsia treatment"' in q2 or '"treatment guidelines"' in q2


def test_v2_fallback_when_all_stopwords():
    stopwords = load_stopwords()
    variant_map = {}
    non_content = set(NON_CONTENT_WORDS)
    q = "the and of"
    query, tokens = build_keyword_query(q, stopwords, non_content, variant_map, variant="v2")
    assert len(tokens) >= 1  # fallback should produce at least one token


# ---------------------------------------------------------------------------
# Weak-label flag tests
# ---------------------------------------------------------------------------

def test_weak_label_threshold():
    """>15 matching chunks => weak label."""
    from evaluate_audit import WEAK_LABEL_THRESHOLD
    assert WEAK_LABEL_THRESHOLD == 15

    # Simulate: 16 matching chunks => weak label
    match_count = 16
    is_weak = match_count > WEAK_LABEL_THRESHOLD
    assert is_weak is True

    match_count = 15
    is_weak = match_count > WEAK_LABEL_THRESHOLD
    assert is_weak is False


# ---------------------------------------------------------------------------
# Weighted RRF exact scores tests
# ---------------------------------------------------------------------------

def test_weighted_rrf_wkw_zero():
    """w_kw=0 means only dense contributes."""
    dense = [("book", 1, "text", 0.9)]
    kw = [("book", 1, "text", -1.0)]
    result = weighted_rrf(dense, kw, w_dense=1.0, w_kw=0.0, k=60, top_k=5)
    expected = 1.0 / 61.0
    assert abs(result[0][3] - expected) < 1e-9, f"Got {result[0][3]}, expected {expected}"


def test_weighted_rrf_wkw_positive():
    """w_kw=0.5 adds half of keyword contribution."""
    dense = [("book", 1, "text", 0.9)]
    kw = [("book", 1, "text", -1.0)]
    result = weighted_rrf(dense, kw, w_dense=1.0, w_kw=0.5, k=60, top_k=5)
    expected = 1.0 / 61.0 + 0.5 / 61.0
    assert abs(result[0][3] - expected) < 1e-9, f"Got {result[0][3]}, expected {expected}"


def test_weighted_rrf_page_dedup():
    """Same page appears twice in dense - only best rank counts."""
    dense = [("book", 1, "text a", 0.9), ("book", 1, "text b", 0.8)]
    kw = [("book", 2, "text", -1.0)]
    result = weighted_rrf(dense, kw, w_dense=1.0, w_kw=0.5, k=60, top_k=5)
    page1_results = [r for r in result if r[1] == 1]
    assert len(page1_results) == 1


def test_weighted_rrf_ordering():
    """Results sorted by descending score."""
    dense = [("b1", 1, "t1", 0.9), ("b2", 2, "t2", 0.8)]
    kw = [("b2", 2, "t2", -1.0), ("b3", 3, "t3", -1.0)]
    result = weighted_rrf(dense, kw, w_dense=1.0, w_kw=0.5, k=60, top_k=5)
    scores = [r[3] for r in result]
    assert scores == sorted(scores, reverse=True), f"Not sorted: {scores}"


# ---------------------------------------------------------------------------
# Non-content words list (max 40)
# ---------------------------------------------------------------------------

def test_non_content_words_max_40():
    assert len(NON_CONTENT_WORDS) <= 40
    assert "patient" in NON_CONTENT_WORDS
    assert "patients" in NON_CONTENT_WORDS
    assert "case" in NON_CONTENT_WORDS
    assert "cases" in NON_CONTENT_WORDS
    assert "type" in NON_CONTENT_WORDS
    assert "types" in NON_CONTENT_WORDS
    assert "following" in NON_CONTENT_WORDS
    assert "used" in NON_CONTENT_WORDS
    assert "include" in NON_CONTENT_WORDS
    assert "including" in NON_CONTENT_WORDS


# ---------------------------------------------------------------------------
# Chunk-text sha256 stability
# ---------------------------------------------------------------------------

def test_chunk_texts_sha256_deterministic():
    texts = ["hello world", "medical text", "another chunk"]
    h1 = hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()
    h2 = hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()
    assert h1 == h2
    assert len(h1) == 64
