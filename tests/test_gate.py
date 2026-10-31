#!/usr/bin/env python3
"""Unit tests for gate threshold logic."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import os  # noqa: E402

from calibrate_gate import content_words, count_keyword_hits  # noqa: E402


def test_content_words_stopwords():
    words = content_words("What is the treatment for postpartum hemorrhage?")
    assert "postpartum" in words
    assert "hemorrhage" in words
    assert "the" not in words
    assert "is" not in words
    assert "for" not in words
    assert "what" not in words


def test_content_words_arabic():
    words = content_words("ما هي أسباب تسمم الحمل؟")
    assert "تسمم" in words
    assert "الحمل" in words
    assert "ما" not in words
    assert "هي" not in words


def test_count_keyword_hits():
    class FakeCur:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            self.calls.append((sql, params))
            class FakeRes:
                def fetchall(self):
                    return []
            return FakeRes()

    # This test just checks the function runs without error on empty text
    cur = FakeCur()
    hits = count_keyword_hits(cur, "postpartum hemorrhage treatment", ["some text about postpartum care"])
    assert hits >= 0


def test_gate_acceptance_logic():
    """Hand-made gate logic: dense >= threshold AND kw_hits >= 1."""
    in_scope = [
        {"dense_top1_score": 0.85, "kw_hits_top3": 2},
        {"dense_top1_score": 0.90, "kw_hits_top3": 0},
        {"dense_top1_score": 0.70, "kw_hits_top3": 1},
    ]
    out_scope = [
        {"dense_top1_score": 0.50, "kw_hits_top3": 0},
        {"dense_top1_score": 0.55, "kw_hits_top3": 1},
        {"dense_top1_score": 0.40, "kw_hits_top3": 0},
    ]

    threshold = 0.62
    in_accept = sum(1 for r in in_scope if r["dense_top1_score"] >= threshold and r["kw_hits_top3"] >= 1)
    out_reject = sum(1 for r in out_scope if not (r["dense_top1_score"] >= threshold and r["kw_hits_top3"] >= 1))

    assert in_accept == 1  # Only first one passes
    assert out_reject == 3  # All rejected
