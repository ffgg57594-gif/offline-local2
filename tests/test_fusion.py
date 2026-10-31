#!/usr/bin/env python3
"""Unit tests for RRF fusion exact scores and gate threshold logic."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import os  # noqa: E402

from evaluate_dense_vs_keyword import rrf_fuse  # noqa: E402


def test_rrf_max_score():
    """With k=60 and two ranked lists, max score = 2/61 = 0.032786..."""
    dense = [("book", 1, "text one", 0.9)]
    fts = [("book", 1, "text one", -1.0)]
    result = rrf_fuse(dense, fts, k=60, top_k=5)
    expected = 2.0 / 61.0
    assert abs(result[0][3] - expected) < 1e-9, f"Got {result[0][3]}, expected {expected}"


def test_rrf_single_list_rank1():
    """A doc at rank 1 in one list only scores 1/61."""
    dense = [("book", 1, "text one", 0.9)]
    fts = [("book", 2, "text two", -1.0)]
    result = rrf_fuse(dense, fts, k=60, top_k=5)
    expected = 1.0 / 61.0
    assert abs(result[0][3] - expected) < 1e-9, f"Got {result[0][3]}, expected {expected}"


def test_rrf_rank_contribution():
    """Doc at rank 0 in dense and rank 2 in fts: 1/61 + 1/63."""
    dense = [("book", 1, "text one", 0.9)]
    fts = [("book", 3, "text three", -1.0), ("book", 2, "text two", -1.0), ("book", 1, "text one", -1.0)]
    result = rrf_fuse(dense, fts, k=60, top_k=5)
    expected = 1.0 / 61.0 + 1.0 / 63.0
    assert abs(result[0][3] - expected) < 1e-9, f"Got {result[0][3]}, expected {expected}"


def test_rrf_ordering():
    """Results must be sorted by descending score."""
    dense = [("b1", 1, "t1", 0.9), ("b2", 2, "t2", 0.8)]
    fts = [("b2", 2, "t2", -1.0), ("b3", 3, "t3", -1.0)]
    result = rrf_fuse(dense, fts, k=60, top_k=5)
    scores = [r[3] for r in result]
    assert scores == sorted(scores, reverse=True), f"Not sorted: {scores}"


def test_rrf_empty_lists():
    """Empty lists produce empty results."""
    result = rrf_fuse([], [], k=60, top_k=5)
    assert result == []


def test_rrf_k_param():
    """With k=10, max score = 2/11."""
    dense = [("book", 1, "t1", 0.9)]
    fts = [("book", 1, "t1", -1.0)]
    result = rrf_fuse(dense, fts, k=10, top_k=5)
    expected = 2.0 / 11.0
    assert abs(result[0][3] - expected) < 1e-9, f"Got {result[0][3]}, expected {expected}"
