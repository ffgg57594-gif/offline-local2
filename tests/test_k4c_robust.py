#!/usr/bin/env python3
"""Unit tests for the K4c robust gate fit (synthetic data, no CI artifacts)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import robust_gate  # noqa: E402
from gate_rule import EPSILON  # noqa: E402


def _rows():
    # 10 answerable and 10 out-of-scope rows.  s1 values are spaced so that a
    # -0.005 shift still leaves at least 9/10 answerable rows accepted, and s3
    # has two observed values so the t3 grid is non-trivial.
    ans_s1 = [0.840, 0.845, 0.850, 0.855, 0.860, 0.865, 0.870, 0.875, 0.880, 0.885]
    oos_s1 = [0.800, 0.805, 0.810, 0.815, 0.820, 0.825, 0.830, 0.835, 0.838, 0.860]
    rows = []
    for i, s1 in enumerate(ans_s1):
        rows.append(
            {
                "group": "in",
                "cls": "IN",
                "id": i + 1,
                "answerable": True,
                "s1_top1": s1,
                "s3_cov_top3": 1.0 if i % 2 == 0 else 0.5,
                "s4_unknown": 0.0,
            }
        )
    for i, s1 in enumerate(oos_s1):
        rows.append(
            {
                "group": "out",
                "cls": "A",
                "id": i + 1,
                "answerable": False,
                "s1_top1": s1,
                "s3_cov_top3": 0.5 if i % 2 == 0 else 0.25,
                "s4_unknown": 0.0,
            }
        )
    return rows


def test_t1_grid_matches_spec():
    grid = robust_gate.t1_grid()
    assert len(grid) == 25
    assert abs(grid[0] - 0.82) <= 1e-12
    assert abs(grid[-1] - 0.88) <= 1e-12
    assert abs((grid[1] - grid[0]) - 0.0025) <= 1e-12


def test_worst_case_bounds_nominal_counts():
    rows = _rows()
    candidates = robust_gate.build_candidates(rows)
    assert candidates
    for c in candidates:
        assert c.worst_acc_count <= c.nominal_acc_count
        assert c.worst_rej_count <= c.nominal_rej_count
        assert c.worst_acc_count >= 0 and c.worst_rej_count >= 0


def test_selected_rule_respects_floor_and_is_on_grid():
    rows = _rows()
    candidates = robust_gate.build_candidates(rows)
    for floor in (0.90, 0.85):
        chosen, tied, plateau = robust_gate.select_preset(candidates, floor)
        assert chosen.worst_acc + 1e-12 >= floor
        assert chosen in tied
        assert any(abs(chosen.t1 - g) <= 1e-12 for g in robust_gate.t1_grid())
        assert chosen.t3 in set(robust_gate.observed_s3(rows))
        assert chosen.k in robust_gate.K_GRID
        assert plateau["t1_min"] <= chosen.t1 <= plateau["t1_max"]
        assert plateau["t3_min"] <= chosen.t3 <= plateau["t3_max"]


def test_sensitivity_shifts_s1_by_delta():
    rows = _rows()
    params = {"t1": 0.84, "t3": 0.5, "k": 0}
    nominal = robust_gate.evaluate_shift(rows, params, 0.0)
    lowered = robust_gate.evaluate_shift(rows, params, -0.01)
    raised = robust_gate.evaluate_shift(rows, params, +0.01)
    # Lower s1 never accepts more answerable rows; higher s1 never rejects more.
    assert lowered[0] <= nominal[0] <= raised[0]
    assert raised[2] <= nominal[2] <= lowered[2]


def test_epsilon_is_applied_to_shifted_comparison():
    rows = [
        {
            "group": "in",
            "cls": "IN",
            "id": 1,
            "answerable": True,
            "s1_top1": 0.84 - EPSILON,
            "s3_cov_top3": 0.5,
            "s4_unknown": 0.0,
        },
        {
            "group": "out",
            "cls": "A",
            "id": 1,
            "answerable": False,
            "s1_top1": 0.84 - 2 * EPSILON,
            "s3_cov_top3": 0.5,
            "s4_unknown": 0.0,
        },
    ]
    accepted, total_ans, rejected, total_oos = robust_gate.evaluate_shift(
        rows, {"t1": 0.84, "t3": 0.5, "k": 0}, 0.0
    )
    assert (accepted, total_ans, rejected, total_oos) == (1, 1, 1, 1)
