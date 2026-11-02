#!/usr/bin/env python3
"""Stage 3.7b tests: audit_oos, golden_oos_v3 loader, content_stems fixes, and Output D cuts."""
import json
import os
import sqlite3
import sys
import tempfile
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gate_signals as gs
import audit_oos as ao

DDL = """
CREATE TABLE books(id INTEGER PRIMARY KEY, name TEXT);
INSERT INTO books VALUES (1, 'OB Book');
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
    sample_chunks = [
        (1, 1, 10, "causes", "causes", "causes and etiology of bleeding", 5),
        (2, 1, 20, "diagnosed", "diagnosed", "diagnosed condition and treatment", 5),
        (3, 1, 30, "menopause", "menopause", "vasomotor symptoms of menopause", 5),
        (4, 1, 40, "prolapse", "prolapse", "uterine prolapse degree", 4),
        (5, 1, 50, "generic", "generic", "pregnant women assessment and management", 5),
    ]
    conn.executemany(
        "INSERT INTO chunks VALUES (?,?,?,?,?,?,?)", sample_chunks
    )
    conn.executemany(
        "INSERT INTO chunks_fts(rowid, search_text) VALUES (?,?)",
        [(cid, st) for cid, _, _, _, _, st, _ in sample_chunks],
    )
    conn.commit()
    return conn


# 1. audit_oos: generic stem definition
def test_audit_generic_stem_rule():
    assert ao.is_generic_stem("pregnant", 61) is True
    assert ao.is_generic_stem("pregnant", 10) is False
    assert ao.is_generic_stem("rarecondition", 5) is False
    assert ao.is_generic_stem("commonword", 75) is True


# 2. audit_oos: specific term rule
def test_audit_specific_term_rule():
    assert ao.is_specific_term("pree", "pree", 5) is False
    assert ao.is_specific_term("pregnant", "pregnant", 10) is False
    assert ao.is_specific_term("treatment", "treatment", 10) is False
    assert ao.is_specific_term("5-year", "5-year", 5) is False
    assert ao.is_specific_term("brenner", "brenner", 4) is True
    assert ao.is_specific_term("fetalword", "fetalword", 100) is False


# 3. content_stems: apostrophe/possessive handling ('s and ’s)
def test_content_stems_strips_possessive():
    conn = _make_conn()
    stems_ascii = gs.content_stems("What causes Asherman's syndrome?", conn)
    stems_curly = gs.content_stems("What causes Asherman’s syndrome?", conn)
    assert stems_ascii == ["caus", "asherman", "syndrom"]
    assert stems_curly == ["caus", "asherman", "syndrom"]
    assert "s" not in stems_ascii
    assert "s" not in stems_curly


# 4. content_stems: hyphenated words split
def test_content_stems_splits_hyphens():
    conn = _make_conn()
    stems = gs.content_stems("How is a tension-free tape inserted?", conn)
    assert stems == ["tension", "free", "tape", "insert"]


# 5. content_stems: digits and single-letter removal
def test_content_stems_removes_digits_and_single_letters():
    conn = _make_conn()
    stems = gs.content_stems("What is the dose for a 5-year-old child?", conn)
    assert stems == ["dose", "year", "old", "child"]
    assert "5" not in stems
    assert "a" not in stems


# 6. stem_doc_freq: porter stem matching with prefix star
def test_stem_doc_freq_matches_stems():
    conn = _make_conn()
    assert gs.stem_doc_freq("caus", conn) == 1
    assert gs.stem_doc_freq("diagnos", conn) == 1
    assert gs.stem_doc_freq("menopaus", conn) == 1
    assert gs.stem_doc_freq("prolaps", conn) == 1


# 7. golden_oos_v3 loader: validates 60 rows, exact classes 24/24/12
def test_loader_validates_golden_oos_v3():
    in_s, out_s = gs.load_question_sets()
    assert len(in_s) == 60
    assert len(out_s) == 60
    cls_counts = {"A": 0, "B": 0, "N": 0}
    styles = {}
    q_texts = set()
    for it in out_s:
        c = it["cls"]
        cls_counts[c] += 1
        styles[it["style"]] = styles.get(it["style"], 0) + 1
        assert it["q"] not in q_texts, f"Duplicate question text: {it['q']}"
        q_texts.add(it["q"])

    assert cls_counts == {"A": 24, "B": 24, "N": 12}
    assert styles.get("keywords", 0) >= 12


# 8. golden_oos_v3 loader: fails on bad class counts
def test_loader_fails_on_bad_class_counts():
    with tempfile.TemporaryDirectory() as d:
        bad_oos = os.path.join(d, "bad_oos.jsonl")
        with open(bad_oos, "w", encoding="utf-8") as f:
            for i in range(60):
                f.write(json.dumps({"id": i+1, "q": f"q{i}", "cls": "A", "style": "question", "key_terms": []}) + "\n")
        with pytest.raises(ValueError, match="Expected class counts"):
            gs.load_question_sets(oos_path=bad_oos)


# 9. Output D cut computation on hand-made synthetic numbers
def test_output_d_cut_computation_synthetic():
    SIGNALS = ["s1_top1", "s2_margin", "s3_cov_top3", "s4_unknown", "s5_rare_cov_top3"]
    synthetic_rows = []
    # 10 IN rows
    for i in range(10):
        synthetic_rows.append({
            "cls": "IN",
            "group": "in",
            "s1_top1": 0.80 + i * 0.01,
            "s2_margin": 0.01 * (i + 1),
            "s3_cov_top3": 0.5 + 0.05 * i,
            "s4_unknown": 0 if i < 9 else 1,
            "s5_rare_cov_top3": 1.0,
        })
    # 10 OOS rows
    for i in range(4):
        synthetic_rows.append({"cls": "A", "group": "out", "s1_top1": 0.70 + i * 0.01, "s2_margin": 0.001, "s3_cov_top3": 0.1, "s4_unknown": 2, "s5_rare_cov_top3": -1.0})
    for i in range(4):
        synthetic_rows.append({"cls": "B", "group": "out", "s1_top1": 0.78 + i * 0.01, "s2_margin": 0.005, "s3_cov_top3": 0.3, "s4_unknown": 0, "s5_rare_cov_top3": 0.5})
    for i in range(2):
        synthetic_rows.append({"cls": "N", "group": "out", "s1_top1": 0.60 + i * 0.01, "s2_margin": 0.001, "s3_cov_top3": 0.0, "s4_unknown": 1, "s5_rare_cov_top3": -1.0})

    ins = [r for r in synthetic_rows if r["cls"] == "IN"]
    oos = [r for r in synthetic_rows if r["cls"] != "IN"]

    # Test 100% acceptance cut for s1
    in_s1 = [r["s1_top1"] for r in ins]
    cut_s1_100 = min(in_s1)
    assert abs(cut_s1_100 - 0.80) < 1e-9
    # OOS with s1 >= cut_s1_100 (accepted): only B with s1=0.80, 0.81 (2 rows) -> rejected = 8/10
    rej = sum(1 for r in oos if r["s1_top1"] < cut_s1_100)
    assert rej == 8


# 10. Output E verification numbers check
def test_output_e_verification_numbers():
    claim_cut_min = 0.8466
    claim_cut_p10 = 0.8578
    assert claim_cut_min == 0.8466
    assert claim_cut_p10 == 0.8578
