#!/usr/bin/env python3
"""K4c: robust refusal-gate fitting shared by the pipeline and analysis.

The K4b presets sat in narrow gaps between observed values.  On-device s1 can
move by roughly 0.001-0.005 between CPU families, which is enough to flip those
presets.  K4c therefore optimises the *worst case* over a deterministic s1
shift set::

    d in (-0.005, 0.0, +0.005)

For every candidate (t1, t3, k) it records:
  * worst-case answerable acceptance = min over d of accepted / 63
  * worst-case OOS rejection        = min over d of rejected / 57
  * nominal values at d = 0

balanaced = maximise worst-case rejection subject to worst-case acceptance
            >= 0.90
strict   = maximise worst-case rejection subject to worst-case acceptance
            >= 0.85

The t1 grid is 0.82..0.88 step 0.0025.  t3 is taken from the observed s3 values
of the same CSV.  k is 0..3.  The comparison epsilon from gate_rule.py is kept.

Ties: choose the point whose t1 is closest to the centre of the tied t1
plateau.  If several t3/k remain, prefer higher worst-case acceptance, then
higher nominal acceptance, then higher nominal rejection, then the smallest k.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from gate_rule import EPSILON

T1_START = 0.82
T1_END = 0.88
T1_STEP = 0.0025
K_GRID = (0, 1, 2, 3)
FIT_DELTAS = (-0.005, 0.0, 0.005)
SENSITIVITY_DELTAS = (-0.01, -0.005, -0.0025, 0.0, 0.0025, 0.005, 0.01)


def t1_grid():
    values = np.arange(T1_START, T1_END + T1_STEP / 2.0, T1_STEP)
    return np.round(values, 10)


def observed_s3(rows):
    return np.array(sorted(set(float(r["s3_cov_top3"]) for r in rows)), dtype=np.float64)


@dataclass(frozen=True)
class Candidate:
    t1: float
    t3: float
    k: int
    n_answerable: int
    n_oos: int
    worst_acc_count: int
    worst_rej_count: int
    nominal_acc_count: int
    nominal_rej_count: int
    per_delta: tuple  # ((d, acc_count, rej_count), ...)

    @property
    def worst_acc(self):
        return self.worst_acc_count / float(self.n_answerable)

    @property
    def worst_rej(self):
        return self.worst_rej_count / float(self.n_oos)

    @property
    def nominal_acc(self):
        return self.nominal_acc_count / float(self.n_answerable)

    @property
    def nominal_rej(self):
        return self.nominal_rej_count / float(self.n_oos)


def _pack(rows):
    ans = [r for r in rows if r["answerable"]]
    oos = [r for r in rows if not r["answerable"]]
    if not ans or not oos:
        raise ValueError("need both answerable and out-of-scope rows")
    return (
        np.array([float(r["s1_top1"]) for r in ans], dtype=np.float64),
        np.array([float(r["s3_cov_top3"]) for r in ans], dtype=np.float64),
        np.array([float(r["s4_unknown"]) for r in ans], dtype=np.float64),
        np.array([float(r["s1_top1"]) for r in oos], dtype=np.float64),
        np.array([float(r["s3_cov_top3"]) for r in oos], dtype=np.float64),
        np.array([float(r["s4_unknown"]) for r in oos], dtype=np.float64),
        len(ans),
        len(oos),
    )


def build_candidates(rows, deltas=FIT_DELTAS):
    """Enumerate every (t1, t3, k) and compute worst/nominal counts."""
    s1_ans, s3_ans, s4_ans, s1_oos, s3_oos, s4_oos, n_ans, n_oos = _pack(rows)
    t1_values = t1_grid()
    t3_values = observed_s3(rows)
    nominal_index = list(deltas).index(0.0)

    out = []
    for k in K_GRID:
        ans_k = s4_ans <= k
        oos_k = s4_oos <= k
        for t3 in t3_values:
            ans_ok3 = ans_k & (s3_ans + EPSILON >= t3)
            oos_ok3 = oos_k & (s3_oos + EPSILON >= t3)
            ans_sorted = np.sort(s1_ans[ans_ok3])
            oos_sorted = np.sort(s1_oos[oos_ok3])

            acc_counts = np.empty((len(t1_values), len(deltas)), dtype=np.int64)
            rej_counts = np.empty_like(acc_counts)
            for j, d in enumerate(deltas):
                threshold = t1_values - d - EPSILON
                acc_counts[:, j] = (
                    len(ans_sorted) - np.searchsorted(ans_sorted, threshold, side="left")
                )
                accepted_oos = (
                    len(oos_sorted) - np.searchsorted(oos_sorted, threshold, side="left")
                )
                rej_counts[:, j] = n_oos - accepted_oos

            worst_acc = acc_counts.min(axis=1)
            worst_rej = rej_counts.min(axis=1)
            for i, t1 in enumerate(t1_values):
                per_delta = tuple(
                    (float(deltas[j]), int(acc_counts[i, j]), int(rej_counts[i, j]))
                    for j in range(len(deltas))
                )
                out.append(
                    Candidate(
                        t1=float(t1),
                        t3=float(t3),
                        k=int(k),
                        n_answerable=n_ans,
                        n_oos=n_oos,
                        worst_acc_count=int(worst_acc[i]),
                        worst_rej_count=int(worst_rej[i]),
                        nominal_acc_count=int(acc_counts[i, nominal_index]),
                        nominal_rej_count=int(rej_counts[i, nominal_index]),
                        per_delta=per_delta,
                    )
                )
    return out


def feasible(candidates, floor):
    return [c for c in candidates if c.worst_acc + 1e-12 >= floor]


def top_candidates(candidates, floor, limit=5):
    """Rank feasible candidates by the K4c objective."""
    pool = feasible(candidates, floor)
    return sorted(
        pool,
        key=lambda c: (
            -c.worst_rej_count,
            -c.worst_acc_count,
            -c.nominal_acc_count,
            -c.nominal_rej_count,
            c.k,
            c.t1,
            c.t3,
        ),
    )[:limit]


def select_preset(candidates, floor):
    """Return ``(chosen, tied, plateau)`` for one preset floor."""
    pool = feasible(candidates, floor)
    if not pool:
        raise ValueError(f"no rule reaches worst-case acceptance floor {floor}")

    best_rej = max(c.worst_rej_count for c in pool)
    tied = [c for c in pool if c.worst_rej_count == best_rej]

    t1_values = sorted(set(c.t1 for c in tied))
    t1_centre = (t1_values[0] + t1_values[-1]) / 2.0
    t1_distance = min(abs(c.t1 - t1_centre) for c in tied)
    near = [c for c in tied if abs(abs(c.t1 - t1_centre) - t1_distance) <= 1e-12]
    chosen = max(
        near,
        key=lambda c: (
            c.worst_acc_count,
            c.nominal_acc_count,
            c.nominal_rej_count,
            -c.k,
            -c.t3,
        ),
    )

    t3_values = sorted(set(c.t3 for c in tied))
    plateau = {
        "tied_count": len(tied),
        "t1_min": t1_values[0],
        "t1_max": t1_values[-1],
        "t1_width": t1_values[-1] - t1_values[0],
        "t1_centre": t1_centre,
        "t1_unique": len(t1_values),
        "t3_min": t3_values[0],
        "t3_max": t3_values[-1],
        "t3_width": t3_values[-1] - t3_values[0],
        "t3_unique": len(t3_values),
        "worst_rej_count": best_rej,
    }
    return chosen, tied, plateau


def fit_preset(rows, floor):
    """Compatibility wrapper: ``(worst_rej, worst_acc, t1, t3, k)`` and ties."""
    candidates = build_candidates(rows)
    chosen, tied, _ = select_preset(candidates, floor)
    tuple_chosen = (
        chosen.worst_rej_count,
        chosen.worst_acc,
        chosen.t1,
        chosen.t3,
        chosen.k,
    )
    tuple_tied = [
        (c.worst_rej_count, c.worst_acc, c.t1, c.t3, c.k) for c in tied
    ]
    return tuple_chosen, tuple_tied


def evaluate_shift(rows, params, d):
    """Counts after shifting every s1 by ``d`` (epsilon included)."""
    from gate_rule import accept

    ans = [r for r in rows if r["answerable"]]
    oos = [r for r in rows if not r["answerable"]]
    accepted = sum(
        1
        for r in ans
        if accept(
            float(r["s1_top1"]) + d,
            float(r["s3_cov_top3"]),
            float(r["s4_unknown"]),
            params,
        )
    )
    rejected = sum(
        1
        for r in oos
        if not accept(
            float(r["s1_top1"]) + d,
            float(r["s3_cov_top3"]),
            float(r["s4_unknown"]),
            params,
        )
    )
    return accepted, len(ans), rejected, len(oos)


def sensitivity(rows, presets, deltas=SENSITIVITY_DELTAS):
    """Return sensitivity rows for each preset and delta."""
    result = {}
    for name, params in presets.items():
        result[name] = []
        for d in deltas:
            accepted, total_ans, rejected, total_oos = evaluate_shift(rows, params, d)
            result[name].append(
                {
                    "d": float(d),
                    "accepted_answerable": accepted,
                    "total_answerable": total_ans,
                    "rejected_oos": rejected,
                    "total_oos": total_oos,
                }
            )
    return result


def run_cv(rows, floors, n_splits=5, n_repeats=30, seed=7):
    """Repeated 5-fold CV with robust refitting on each training fold.

    Both presets see the same random splits (one permutation per repeat), so
    their held-out numbers are directly comparable.  For each validation fold we
    report the nominal (d = 0) counts and the worst case over ``FIT_DELTAS``.
    """
    from gate_rule import accept

    rng = np.random.RandomState(seed)
    ans_idx = np.array([i for i, r in enumerate(rows) if r["answerable"]])
    oos_idx = np.array([i for i, r in enumerate(rows) if not r["answerable"]])

    acc_lists = {name: [] for name, _ in floors}
    rej_lists = {name: [] for name, _ in floors}
    worst_acc_lists = {name: [] for name, _ in floors}
    worst_rej_lists = {name: [] for name, _ in floors}

    for _ in range(n_repeats):
        ans_shuff = rng.permutation(ans_idx)
        oos_shuff = rng.permutation(oos_idx)
        ans_splits = np.array_split(ans_shuff, n_splits)
        oos_splits = np.array_split(oos_shuff, n_splits)

        for f in range(n_splits):
            val_ans_set = set(int(i) for i in ans_splits[f])
            val_oos_set = set(int(i) for i in oos_splits[f])
            train_rows = [
                rows[i]
                for i in range(len(rows))
                if i not in val_ans_set and i not in val_oos_set
            ]
            val_ans = [rows[i] for i in val_ans_set]
            val_oos = [rows[i] for i in val_oos_set]

            for name, floor in floors:
                chosen, _ = fit_preset(train_rows, floor)
                params = {"t1": chosen[2], "t3": chosen[3], "k": chosen[4]}

                def counts(d):
                    a = sum(
                        1
                        for r in val_ans
                        if accept(
                            float(r["s1_top1"]) + d,
                            float(r["s3_cov_top3"]),
                            float(r["s4_unknown"]),
                            params,
                        )
                    )
                    o = sum(
                        1
                        for r in val_oos
                        if not accept(
                            float(r["s1_top1"]) + d,
                            float(r["s3_cov_top3"]),
                            float(r["s4_unknown"]),
                            params,
                        )
                    )
                    return a / len(val_ans), o / len(val_oos)

                nominal_acc, nominal_rej = counts(0.0)
                shifted = [counts(d) for d in FIT_DELTAS]
                acc_lists[name].append(nominal_acc)
                rej_lists[name].append(nominal_rej)
                worst_acc_lists[name].append(min(x[0] for x in shifted))
                worst_rej_lists[name].append(min(x[1] for x in shifted))

    results = {}
    for name, _ in floors:
        results[name] = {
            "acc_mean": float(np.mean(acc_lists[name])),
            "acc_min": float(np.min(acc_lists[name])),
            "rej_mean": float(np.mean(rej_lists[name])),
            "rej_min": float(np.min(rej_lists[name])),
            "worst_acc_mean": float(np.mean(worst_acc_lists[name])),
            "worst_acc_min": float(np.min(worst_acc_lists[name])),
            "worst_rej_mean": float(np.mean(worst_rej_lists[name])),
            "worst_rej_min": float(np.min(worst_rej_lists[name])),
        }
    return results
