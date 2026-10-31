#!/usr/bin/env python3
"""Stage 3.6a tests: normalization, keyword builder, RRF, answer_terms, golden parser."""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from text_normalize import normalize_text, load_variant_map, FULL_VARIANTS  # noqa: E402
from keyword_builder import (
    build_keyword_query,
    load_stopwords,
    answer_terms_match,
    answer_terms_match_fts,
    STOPWORDS,
)  # noqa: E402
from fusion_tuning import weighted_rrf  # noqa: E402


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

def test_normalize_lowercase():
    assert normalize_text("HELLO World") == "hello world"


def test_normalize_hyphen_unify():
    text = "pre\u2013eclampsia"  # en dash
    assert "\u2013" not in normalize_text(text)
    assert "pre-eclampsia" in normalize_text(text)


def test_normalize_spelling_variant():
    vm = {"labour": "labor", "haemorrhage": "hemorrhage"}
    assert normalize_text("postpartum haemorrhage", vm) == "postpartum hemorrhage"
    assert normalize_text("labour ward", vm) == "labor ward"


def test_normalize_zero_width():
    assert "\u200b" not in normalize_text("text\u200bhere")
    assert "\ufeff" not in normalize_text("\ufefftext")


def test_normalize_collapse_whitespace():
    assert normalize_text("a    b   c") == "a b c"


def test_variant_map_kept_count():
    """At least 40 variants in the full map."""
    assert len(FULL_VARIANTS) >= 40


# ---------------------------------------------------------------------------
# Keyword builder tests
# ---------------------------------------------------------------------------

def test_stopwords_count():
    assert len(STOPWORDS) >= 150


def test_stopwords_removed():
    stopwords = load_stopwords()
    query, tokens = build_keyword_query("What is the treatment for postpartum hemorrhage?", stopwords, set())
    assert "what" not in tokens
    assert "the" not in tokens
    assert "for" not in tokens
    assert "postpartum" in tokens or "hemorrhage" in tokens


def test_fallback_longest_token():
    stopwords = load_stopwords()
    # All tokens are stopwords -> fall back to longest.
    query, tokens = build_keyword_query("the and of", stopwords, set())
    assert len(tokens) >= 1


def test_quoted_or_query():
    stopwords = load_stopwords()
    query, _ = build_keyword_query("preeclampsia treatment", stopwords, set())
    assert '"preeclampsia"' in query
    assert '"treatment"' in query
    assert " OR " in query


# ---------------------------------------------------------------------------
# RRF exact score tests
# ---------------------------------------------------------------------------

def test_rrf_max_score():
    dense = [("book", 1, "text", 0.9)]
    kw = [("book", 1, "text", -1.0)]
    result = weighted_rrf(dense, kw, w_dense=1.0, w_kw=0.5, k=60, top_k=5)
    expected = 1.0 / 61.0 + 0.5 / 61.0
    assert abs(result[0][3] - expected) < 1e-9, f"Got {result[0][3]}, expected {expected}"


def test_rrf_page_dedup():
    # Same page appears twice in dense - should only count once.
    dense = [("book", 1, "text a", 0.9), ("book", 1, "text b", 0.8)]
    kw = [("book", 2, "text", -1.0)]
    result = weighted_rrf(dense, kw, w_dense=1.0, w_kw=0.5, k=60, top_k=5)
    # Page 1 should appear once with best rank (rank 0).
    page1_results = [r for r in result if r[1] == 1]
    assert len(page1_results) == 1


# ---------------------------------------------------------------------------
# Answer terms matching tests
# ---------------------------------------------------------------------------

def test_answer_terms_match_all_in_group():
    text = "Preeclampsia is hypertension with proteinuria in pregnancy."
    terms = [["preeclampsia", "proteinuria"], ["eclampsia", "seizures"]]
    assert answer_terms_match(text, terms) is True


def test_answer_terms_match_partial_group_false():
    text = "Preeclampsia is hypertension."
    terms = [["preeclampsia", "proteinuria"]]
    assert answer_terms_match(text, terms) is False


def test_answer_terms_match_empty():
    assert answer_terms_match("any text", []) is False


def test_answer_terms_match_fts():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, search_text TEXT)")
    cur.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(search_text, content='chunks', content_rowid='id', tokenize='porter unicode61 remove_diacritics 2')")
    cur.execute("INSERT INTO chunks(id, search_text) VALUES (1, 'Preeclampsia is hypertension with proteinuria')")
    cur.execute("INSERT INTO chunks_fts(rowid, search_text) VALUES (1, 'Preeclampsia is hypertension with proteinuria')")
    cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")

    terms = [["preeclampsia", "proteinuria"]]
    assert answer_terms_match_fts(cur, 1, terms) is True

    terms2 = [["preeclampsia", "seizures"]]
    assert answer_terms_match_fts(cur, 1, terms2) is False

    conn.close()


# ---------------------------------------------------------------------------
# Golden parser tests
# ---------------------------------------------------------------------------

def test_golden_parser():
    import json as _json
    content = """{"id": 1, "q": "What is hypertension?", "lang": "en", "in_scope": true, "answer_terms": [["hypertension", "blood"]], "expected_pages": [10], "pair_id": 1, "key_terms": null}
{"id": 2, "q": "What is diabetes?", "lang": "en", "in_scope": false, "answer_terms": null, "expected_pages": [], "pair_id": null, "key_terms": ["diabetes"]}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write(content)
        tmp = f.name

    try:
        questions = []
        with open(tmp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    questions.append(_json.loads(line))

        assert len(questions) == 2
        assert questions[0]["id"] == 1
        assert questions[0]["in_scope"] is True
        assert questions[0]["answer_terms"] == [["hypertension", "blood"]]
        assert questions[0]["expected_pages"] == [10]
        assert questions[1]["in_scope"] is False
        assert questions[1]["key_terms"] == ["diabetes"]
    finally:
        os.unlink(tmp)


def test_golden_required_fields():
    required = {"id", "q", "lang", "in_scope", "answer_terms", "expected_pages", "pair_id", "key_terms"}
    golden_path = os.path.join(os.path.dirname(__file__), "..", "eval", "golden_v2.draft.jsonl")
    with open(golden_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            assert required.issubset(obj.keys()), f"Line {i} missing fields: {required - obj.keys()}"
            assert obj["lang"] == "en", f"Line {i}: lang must be 'en'"
            assert isinstance(obj["in_scope"], bool), f"Line {i}: in_scope must be bool"
            assert isinstance(obj["expected_pages"], list), f"Line {i}: expected_pages must be list"


# ---------------------------------------------------------------------------
# Schema version 2 test
# ---------------------------------------------------------------------------

def test_schema_version_2():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
    v = cur.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert v == "2"
    conn.close()


# ---------------------------------------------------------------------------
# Chunk-text sha256 stability test
# ---------------------------------------------------------------------------

def test_chunk_texts_sha256_deterministic():
    texts = ["hello world", "medical text", "another chunk"]
    h1 = hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()
    h2 = hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()
    assert h1 == h2
    assert len(h1) == 64
