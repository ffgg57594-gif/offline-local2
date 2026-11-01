#!/usr/bin/env python3
"""Stage 3.6d tests: metric correctness (MRR, hit@k, LENIENT vs STRICT, TARGET-ONLY).

These tests use hand-made rankings (5-tuples: chunk_id, name, page, text, score)
and would catch regressions in:
  - MRR (a miss must lower MRR; denominator is ALL questions, misses contribute 0).
  - hit@k rates.
  - LENIENT >= STRICT, with a case where they differ (adjacent chunk flips a miss).
  - TARGET-ONLY excludes alt_chunk_ids.
"""
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import os  # noqa: E402

from evaluate_golden_v3 import (  # noqa: E402
    recall_at_k,
    mrr_at_k,
    strict_hit_at_k,
    lenient_hit_at_k,
    target_only_hit_at_k,
)


def _row(results, target):
    return {"results": results, "target": target}


def _hit_func(k):
    return lambda r, kk=k: strict_hit_at_k(r["results"], r["target"], [], kk)


# ---------------------------------------------------------------------------
# MRR
# ---------------------------------------------------------------------------

def test_mrr_miss_lowers_mrr():
    """MRR over ALL questions: a miss contributes 0 and lowers the mean."""
    # All 5 hit at rank 1 -> MRR = 1.0.
    rows_all_hit = [_row([(t, "book", 7, "text", 0.9)], t) for t in range(1, 6)]
    assert abs(mrr_at_k(rows_all_hit, _hit_func(10), 10) - 1.0) < 1e-9

    # One question misses -> MRR = 4/5 = 0.8 (miss contributes 0).
    rows_one_miss = [_row([(t, "book", 7, "text", 0.9)], t) for t in range(1, 5)]
    rows_one_miss.append(_row([(999, "book", 7, "text", 0.9)], 50))  # misses
    mrr = mrr_at_k(rows_one_miss, _hit_func(10), 10)
    assert abs(mrr - 0.8) < 1e-9, f"Expected MRR 0.8 with one miss, got {mrr}"

    # Denominator is ALL questions (5), not only the 4 that hit.
    assert mrr < 1.0


def test_hit_at_k():
    """recall_at_k hit rates over hand-made rankings."""
    # 3 hit at rank 1; 1 hits at rank 2; 1 misses entirely.
    rows = [
        _row([(1, "book", 7, "t", 0.9)], 1),
        _row([(2, "book", 7, "t", 0.9)], 2),
        _row([(3, "book", 7, "t", 0.9)], 3),
        _row([(4, "book", 7, "t", 0.9)], 4),
        _row([(999, "book", 7, "t", 0.9)], 90),  # misses
    ]
    hit1, n = recall_at_k(rows, _hit_func(1), 1)
    assert n == 5
    assert abs(hit1 - 0.6) < 1e-9  # 3/5 at rank 1
    hit3, _ = recall_at_k(rows, _hit_func(3), 3)
    assert abs(hit3 - 0.8) < 1e-9  # 4/5 within top-3
    hit5, _ = recall_at_k(rows, _hit_func(5), 5)
    assert abs(hit5 - 0.8) < 1e-9  # still 4/5 within top-5 (one misses entirely)


# ---------------------------------------------------------------------------
# LENIENT vs STRICT
# ---------------------------------------------------------------------------

def test_lenient_ge_strict_and_can_differ():
    """LENIENT >= STRICT, and a case where they differ via an adjacent chunk."""
    chunk_index = {
        1: ("book", "name", 7, "text one"),
        2: ("book", "name", 7, "text two"),
        3: ("book", "name", 8, "text three"),
    }
    # Target 1 not in results, but adjacent chunk 2 (same page 7) is at rank 1.
    results = [(2, "book", 7, "text two", 0.9)]
    strict = strict_hit_at_k(results, 1, [], 5)
    lenient = lenient_hit_at_k(results, 1, [], chunk_index, 5)
    assert strict is None, "STRICT should miss (target not retrieved)"
    assert lenient == 1, "LENIENT should hit via adjacent chunk 2 on same page"

    # Across many hand-made cases, LENIENT hit rate >= STRICT hit rate.
    cases = [
        ([(2, "book", 7, "t", 0.9)], 1),   # adjacent same page -> lenient hits
        ([(3, "book", 8, "t", 0.9)], 1),   # adjacent but diff page -> lenient misses
        ([(1, "book", 7, "t", 0.9)], 1),   # strict hits
        ([(9, "book", 7, "t", 0.9)], 1),   # neither strict nor lenient
    ]
    strict_hits = 0
    lenient_hits = 0
    for results, target in cases:
        if strict_hit_at_k(results, target, [], 5) is not None:
            strict_hits += 1
        if lenient_hit_at_k(results, target, [], chunk_index, 5) is not None:
            lenient_hits += 1
    assert lenient_hits >= strict_hits


def test_target_only_excludes_alts():
    """TARGET-ONLY hits the target chunk only, never an alt_chunk_id."""
    results = [(4, "book", 7, "text four", 0.9), (1, "book", 7, "text one", 0.8)]
    # alt_chunk_ids includes chunk 1; target_only must NOT count it for target 4.
    assert target_only_hit_at_k(results, 4, [1], 2) == 1  # target chunk 4 at rank 1
    assert target_only_hit_at_k(results, 1, [4], 2) == 2  # target chunk 1 at rank 2
    # Target not present, alt present -> TARGET-ONLY misses.
    assert target_only_hit_at_k(results, 9, [1, 4], 5) is None


if __name__ == "__main__":
    test_mrr_miss_lowers_mrr()
    test_hit_at_k()
    test_lenient_ge_strict_and_can_differ()
    test_target_only_excludes_alts()
    print("All Stage 3.6d tests passed.")
