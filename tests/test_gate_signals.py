#!/usr/bin/env python3
"""Stage 3.7a tests: gate signal module on a tiny synthetic schema-v2 database.

6 chunks, 2 books. A fake embedder returns fixed 2-d vectors so the dense
ranking is fully controlled. No ONNX model, numpy, or real corpus needed.
"""
import json
import math
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from gate_signals import (  # noqa: E402
    RARE_MAX_DF,
    RARE_MIN_DF,
    DB_PATH,
    GOLDEN_V2,
    GOLDEN_V3,
    compute_signals,
    content_stems,
    fts_stem,
    load_question_sets,
    stem_doc_freq,
)

# ---------------------------------------------------------------------------
# Synthetic schema-v2 database: 6 chunks, 2 books
# ---------------------------------------------------------------------------

CHUNKS = [
    (1, 1, 7, "postpartum care", "bleeding", "postpartum hemorrhage", 2),
    (2, 1, 7, "uterine atony", "uterine atony", "uterine atony after delivery", 4),
    (3, 1, 8, "fetal monitor", "fetal monitor", "fetal heart rate monitoring", 4),
    (4, 1, 8, "normal labor", "normal labor", "normal labor and delivery", 4),
    (5, 2, 15, "gestational diabetes", "diabetes diet", "gestational diabetes diet", 3),
    (6, 2, 15, "prenatal care", "prenatal vitamins", "prenatal vitamins and folic acid", 4),
]

DDL = """
CREATE TABLE books(id INTEGER PRIMARY KEY, name TEXT);
INSERT INTO books VALUES (1, 'OB Book'), (2, 'OB Book');
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY, book_id INTEGER, page INTEGER, section TEXT,
  text TEXT, search_text TEXT, word_count INTEGER
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    search_text, content='chunks', content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
INSERT INTO meta(key, value) VALUES ('schema_version','2');
"""


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    conn.executemany(
        "INSERT INTO chunks(id, book_id, page, section, text, search_text, word_count) "
        "VALUES (?,?,?,?,?,?,?)", CHUNKS,
    )
    conn.executemany(
        "INSERT INTO chunks_fts(rowid, search_text) VALUES (?,?)",
        [(cid, st) for cid, _, _, _, _, st, _ in CHUNKS],
    )
    conn.commit()
    return conn


# Fixed 2-d embeddings, chunk id -> vector.
CHUNK_VECS = [
    [1.0, 0.0],   # chunk 1
    [0.5, 0.5],   # chunk 2 (cosine 1/sqrt(2) with QVEC)
    [0.0, 1.0],   # chunk 3
    [0.0, 0.5],   # chunk 4
    [0.0, 0.0],   # chunk 5
    [0.0, 0.0],   # chunk 6
]
QVEC = [1.0, 0.0]  # top1 = chunk 1 (1.0), top2 = chunk 2 (0.5)


def _fake_embed(question):
    return list(QVEC)


# Expected stems, verified against the real FTS5 porter tokenizer.
# "postpartum hemorrhage treatment" -> postpartum, hemorrhag, treatment
QUESTION_A = "postpartum hemorrhage treatment"
STEMS_A = ["postpartum", "hemorrhag", "treatment"]
# "zzzqwerty unknownword" -> stems not in corpus
QUESTION_B = "zzzqwerty unknownword"
STEMS_B = ["zzzqwerti", "unknownword"]
# stopwords only
QUESTION_C = "the is a of and how what"
STEMS_C = []
# "fetal heart monitor" -> fetal, heart, monitor (all in chunk 3)
QUESTION_D = "fetal heart monitor"
STEMS_D = ["fetal", "heart", "monitor"]


def _signals(q, stems, **kwargs):
    conn = _make_conn()
    return compute_signals(
        q, conn=conn,
        embeddings=CHUNK_VECS,
        chunk_meta=[(cid, "OB Book", page, text)
                    for cid, _, page, _, text, _, _ in CHUNKS],
        embed_query=_fake_embed, **kwargs,
    ), conn


# ---------------------------------------------------------------------------
# load_question_sets
# ---------------------------------------------------------------------------

def test_load_question_sets_returns_60_and_60():
    in_scope, out_of_scope = load_question_sets()
    assert len(in_scope) == 60, len(in_scope)
    assert len(out_of_scope) == 60, len(out_of_scope)
    for q in in_scope:
        assert set(q.keys()) == {"id", "q"}, q
    for q in out_of_scope:
        assert set(q.keys()) == {"id", "q", "key_terms"}, q
        assert isinstance(q["key_terms"], list)


def test_load_question_sets_fails_on_bad_counts():
    with tempfile.TemporaryDirectory() as d:
        bad_v3 = os.path.join(d, "golden_v3.draft.jsonl")
        bad_v2 = os.path.join(d, "golden_v2.draft.jsonl")
        with open(bad_v3, "w", encoding="utf-8") as f:
            for i in range(59):
                f.write(json.dumps({"id": i, "q": f"q{i}", "in_scope": True}) + "\n")
        with open(bad_v2, "w", encoding="utf-8") as f:
            for i in range(60):
                f.write(json.dumps({"id": i, "q": f"q{i}", "in_scope": False,
                                    "key_terms": ["x"]}) + "\n")
        import gate_signals as gs
        orig_v3, orig_v2 = gs.GOLDEN_V3, gs.GOLDEN_V2
        gs.GOLDEN_V3, gs.GOLDEN_V2 = bad_v3, bad_v2
        try:
            try:
                load_question_sets()
                raise AssertionError("expected ValueError for 59 in-scope questions")
            except ValueError as e:
                assert "59" in str(e) and "60" in str(e), str(e)
        finally:
            gs.GOLDEN_V3, gs.GOLDEN_V2 = orig_v3, orig_v2


# ---------------------------------------------------------------------------
# content_stems / fts_stem
# ---------------------------------------------------------------------------

def test_content_stems_removes_stopwords_and_stems():
    conn = _make_conn()
    stems = content_stems(QUESTION_A, conn)
    assert stems == STEMS_A, stems
    # stopwords removed: "the", "is"
    stems = content_stems("The the postpartum hemorrhage is bad", conn)
    assert stems == ["postpartum", "hemorrhag", "bad"], stems


def test_content_stems_unique_and_ordered():
    conn = _make_conn()
    stems = content_stems("postpartum postpartum hemorrhage hemorrhage", conn)
    assert stems == ["postpartum", "hemorrhag"], stems
    # order follows first occurrence
    stems = content_stems("fetal postpartum hemorrhage", conn)
    assert stems == ["fetal", "postpartum", "hemorrhag"], stems


def test_content_stems_matches_fts5_porter_directly():
    """content_stems must equal the stems the FTS5 porter tokenizer produces."""
    conn = _make_conn()
    samples = ["pregnancy", "hemorrhage", "uterine", "delivery", "monitoring",
               "diabetes", "vitamins", "running", "ran"]
    for word in samples:
        assert content_stems(word, conn) == [fts_stem(word, conn)], word


# ---------------------------------------------------------------------------
# stem_doc_freq
# ---------------------------------------------------------------------------

def test_stem_doc_freq_counts_matching_chunks():
    conn = _make_conn()
    # "postpartum" -> postpartum: chunk 1 only
    assert stem_doc_freq("postpartum", conn) == 1
    # "delivery" -> deliveri: chunks 2 and 4
    assert stem_doc_freq("deliveri", conn) == 2
    # unknown stem: 0
    assert stem_doc_freq("zzzqwerti", conn) == 0
    # raw tokens are stemmed before matching: "deliveries" -> deliveri
    assert stem_doc_freq("deliveries", conn) == 2


def test_stem_doc_freq_is_cached():
    conn = _make_conn()
    assert stem_doc_freq("postpartum", conn) == 1
    assert stem_doc_freq("postpartum", conn) == 1
    assert stem_doc_freq("fetal", conn) == 1


# ---------------------------------------------------------------------------
# compute_signals
# ---------------------------------------------------------------------------

def test_compute_signals_coverage_and_margin():
    sig, _ = _signals(QUESTION_A, STEMS_A)
    assert abs(sig["s1_top1"] - 1.0) < 1e-9
    assert abs(sig["s2_margin"] - (1.0 - 1.0 / math.sqrt(2))) < 1e-9
    # postpartum (chunk 1) and hemorrhag (chunk 1) covered; treatment not in top-3
    assert abs(sig["s3_cov_top3"] - 2 / 3) < 1e-9
    # "treatment" occurs in no chunk -> unknown
    assert sig["s4_unknown"] == 1
    # postpartum and hemorrhag are rare (df 1) and covered; treatment is unknown
    assert sig["n_rare"] == 2
    assert abs(sig["s5_rare_cov_top3"] - 1.0) < 1e-9
    assert sig["n_stems"] == 3


def test_compute_signals_all_unknown():
    sig, _ = _signals(QUESTION_B, STEMS_B)
    assert sig["n_stems"] == 2
    assert sig["s3_cov_top3"] == 0.0
    assert sig["s4_unknown"] == 2
    assert sig["n_rare"] == 0
    assert sig["s5_rare_cov_top3"] == -1.0


def test_compute_signals_no_stems():
    sig, _ = _signals(QUESTION_C, STEMS_C)
    assert sig["n_stems"] == 0
    assert sig["s3_cov_top3"] == 0.0
    assert sig["s4_unknown"] == 0
    assert sig["n_rare"] == 0
    assert sig["s5_rare_cov_top3"] == -1.0


def test_compute_signals_full_coverage():
    sig, _ = _signals(QUESTION_D, STEMS_D)
    assert abs(sig["s3_cov_top3"] - 1.0) < 1e-9
    assert sig["s4_unknown"] == 0
    assert sig["n_rare"] == 3
    assert abs(sig["s5_rare_cov_top3"] - 1.0) < 1e-9


def test_compute_signals_margin_single_chunk():
    sig, _ = _signals(QUESTION_A, STEMS_A)
    conn = _make_conn()
    one = compute_signals(
        QUESTION_A, conn=conn,
        embeddings=[CHUNK_VECS[0]],
        chunk_meta=[(CHUNKS[0][0], "OB Book", CHUNKS[0][2], CHUNKS[0][4])],
        embed_query=_fake_embed,
    )
    assert abs(one["s2_margin"] - one["s1_top1"]) < 1e-9


def test_compute_signals_exact_fields():
    sig, _ = _signals(QUESTION_A, STEMS_A)
    assert set(sig.keys()) == {
        "s1_top1", "s2_margin", "s3_cov_top3", "s4_unknown",
        "s5_rare_cov_top3", "n_stems", "n_rare",
    }
    assert isinstance(sig["s1_top1"], float)
    assert isinstance(sig["s4_unknown"], int)
    assert isinstance(sig["n_stems"], int)


def test_rare_boundaries_use_doc_freq():
    """df 1..24 inclusive counts as rare; with 6 chunks every stem here is rare."""
    conn = _make_conn()
    assert RARE_MIN_DF == 1 and RARE_MAX_DF == 24
    sig, _ = _signals(QUESTION_A, STEMS_A)
    assert sig["n_stems"] == 3
    assert sig["n_rare"] == 2  # "treatment" has df 0, so it is unknown, not rare


if __name__ == "__main__":
    test_load_question_sets_returns_60_and_60()
    test_load_question_sets_fails_on_bad_counts()
    test_content_stems_removes_stopwords_and_stems()
    test_content_stems_unique_and_ordered()
    test_content_stems_matches_fts5_porter_directly()
    test_stem_doc_freq_counts_matching_chunks()
    test_stem_doc_freq_is_cached()
    test_compute_signals_coverage_and_margin()
    test_compute_signals_all_unknown()
    test_compute_signals_no_stems()
    test_compute_signals_full_coverage()
    test_compute_signals_margin_single_chunk()
    test_compute_signals_exact_fields()
    test_rare_boundaries_use_doc_freq()
    print("All tests/test_gate_signals.py checks passed.")
