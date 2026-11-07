#!/usr/bin/env python3
"""Stage 3.7c / K4b: Fit refusal gate presets (balanced, strict) and run repeated CV.

Reads eval/gate_signals.csv and eval/label_fixes.json.

K4b changes
-----------
* Candidate thresholds are the midpoints between adjacent *observed* signal
  values.  A threshold is never equal to an observed value.
* The decision comparison uses the shared 1e-6 epsilon from gate_rule.py:
  ``s1 + 1e-6 >= t1`` and ``s3 + 1e-6 >= t3``.
* The previous (pre-K4b) presets are evaluated on the new data and reported.
* The hard-coded balanced t1 override from Stage 3.7e is removed.

Presets:
  balanced: best OOS rejection with answerable acceptance >= 0.95
  strict:   best OOS rejection with answerable acceptance >= 0.90
Tie-breaking:
  highest acceptance -> median t1 of the tied plateau.

Outputs:
  app/src/main/assets/gate_config.json
  app/src/main/assets/gate_reference.json
  build/reports/k4b/gate_refit_report.json
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate_rule import EPSILON, accept

CSV_PATH = os.path.join("eval", "gate_signals.csv")
FIXES_PATH = os.path.join("eval", "label_fixes.json")
OLD_CONFIG_PATH = os.path.join("eval", "gate_config_old.json")
CONFIG_OUT = os.path.join("app", "src", "main", "assets", "gate_config.json")
REFERENCE_OUT = os.path.join("app", "src", "main", "assets", "gate_reference.json")
REPORT_OUT = os.path.join("build", "reports", "k4b", "gate_refit_report.json")

# Pre-K4b presets, used only when eval/gate_config_old.json is absent.
OLD_PRESETS_FALLBACK = {
    "balanced": {"t1": 0.8375, "t3": 0.571429, "k": 0},
    "strict": {"t1": 0.8525, "t3": 0.571429, "k": 0},
}

# Keep the chosen midpoint away from both observed values by at least this
# much.  Kotlin and Python s1 differ by ~1e-6 on the CI runners; a 5e-6 gap
# keeps rounding noise from flipping a decision while still satisfying the
# strict midpoint rule.
MIN_CANDIDATE_MARGIN = 5e-6


def load_labeled_signals(csv_path=CSV_PATH, fixes_path=FIXES_PATH):
    fixes_by_id = set()
    if os.path.exists(fixes_path):
        with open(fixes_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for fix in data.get("fixes", []):
                if fix.get("action") == "answered_by_book":
                    fixes_by_id.add(int(fix["id"]))

    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        cid = int(r["id"])
        cls = r["cls"]
        if cls == "IN" or (cls == "B" and cid in fixes_by_id):
            r["answerable"] = True
        else:
            r["answerable"] = False

    return rows


def midpoint_candidates(observed, min_margin=MIN_CANDIDATE_MARGIN):
    """Midpoints between adjacent distinct observed values.

    Candidates equal to any observed value are discarded.  Candidates whose
    distance to both neighbours is below ``min_margin`` are preferred away
    from; if that would leave no candidate, the margin requirement is relaxed.
    """
    vals = sorted(set(float(v) for v in observed))
    all_midpoints = []
    for a, b in zip(vals, vals[1:]):
        m = (a + b) / 2.0
        if all(abs(m - v) > 1e-12 for v in vals):
            all_midpoints.append(m)
    if not all_midpoints:
        return []

    def far_enough(m):
        return min(abs(m - v) for v in vals) >= min_margin

    preferred = [m for m in all_midpoints if far_enough(m)]
    return preferred if preferred else all_midpoints


def _pack(rows):
    ans = [r for r in rows if r["answerable"]]
    oos = [r for r in rows if not r["answerable"]]
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


def fit_preset(rows, floor=0.95, min_margin=MIN_CANDIDATE_MARGIN):
    """Fit one preset and return ``(rej, acc_fraction, t1, t3, k)``.

    Both thresholds are midpoints between adjacent observed values, so neither
    can equal an observed value.
    """
    s1_ans, s3_ans, s4_ans, s1_oos, s3_oos, s4_oos, n_ans, n_oos = _pack(rows)
    if n_ans == 0 or n_oos == 0:
        raise ValueError("fit_preset requires both answerable and out-of-scope rows")

    observed_s1 = np.concatenate([s1_ans, s1_oos])
    observed_s3 = np.concatenate([s3_ans, s3_oos])
    t1_grid = np.array(midpoint_candidates(observed_s1, min_margin), dtype=np.float64)
    t3_grid = np.array(midpoint_candidates(observed_s3, min_margin), dtype=np.float64)
    if len(t1_grid) == 0 or len(t3_grid) == 0:
        raise ValueError("no midpoint candidates available")

    k_grid = [0, 1, 2, 3]
    best_rej = -1
    best_acc = -1.0
    tied_rules = []

    # searchsorted works on each (k, t3) subset; the t1 grid is vectorised.
    t1_shifted = t1_grid - EPSILON
    for k in k_grid:
        ans_k = s4_ans <= k
        oos_k = s4_oos <= k
        for t3 in t3_grid:
            ans_ok3 = ans_k & (s3_ans + EPSILON >= t3)
            oos_ok3 = oos_k & (s3_oos + EPSILON >= t3)
            a_sel = np.sort(s1_ans[ans_ok3])
            o_sel = np.sort(s1_oos[oos_ok3])

            acc_counts = len(a_sel) - np.searchsorted(a_sel, t1_shifted, side="left")
            # OOS rejected = all OOS minus those accepted by all three signals.
            accepted_oos = len(o_sel) - np.searchsorted(o_sel, t1_shifted, side="left")
            rej_counts = n_oos - accepted_oos
            acc_fracs = acc_counts / float(n_ans)

            valid = acc_fracs >= floor - 1e-12
            if not valid.any():
                continue
            local_rej = int(np.max(rej_counts[valid]))
            if local_rej < best_rej:
                continue
            for idx in np.nonzero(valid & (rej_counts == local_rej))[0]:
                acc = float(acc_fracs[idx])
                entry = (local_rej, acc, float(t1_grid[idx]), float(t3), int(k))
                if local_rej > best_rej:
                    best_rej = local_rej
                    best_acc = acc
                    tied_rules = [entry]
                elif acc > best_acc + 1e-15:
                    best_acc = acc
                    tied_rules = [entry]
                elif abs(acc - best_acc) <= 1e-15:
                    tied_rules.append(entry)

    if not tied_rules:
        if min_margin > 0:
            return fit_preset(rows, floor=floor, min_margin=0.0)
        raise ValueError(f"no rule reaches floor {floor}")

    # Plateau tie-breaker: median t1 of the tied plateau.
    t1_vals = sorted(r[2] for r in tied_rules)
    median_t1 = float(np.median(t1_vals))
    chosen = min(tied_rules, key=lambda r: (abs(r[2] - median_t1), r[4], r[3]))
    return chosen, tied_rules


def run_cv(rows, n_splits=5, n_repeats=30, seed=7):
    rng = np.random.RandomState(seed)
    ans_idx = np.array([i for i, r in enumerate(rows) if r["answerable"]])
    oos_idx = np.array([i for i, r in enumerate(rows) if not r["answerable"]])

    results = {}
    for floor, name in [(0.95, "balanced"), (0.90, "strict")]:
        acc_list = []
        rej_list = []
        for rep in range(n_repeats):
            ans_shuff = rng.permutation(ans_idx)
            oos_shuff = rng.permutation(oos_idx)
            ans_splits = np.array_split(ans_shuff, n_splits)
            oos_splits = np.array_split(oos_shuff, n_splits)

            for f in range(n_splits):
                val_ans_set = set(int(i) for i in ans_splits[f])
                val_oos_set = set(int(i) for i in oos_splits[f])

                train_rows = [
                    rows[i] for i in range(len(rows))
                    if i not in val_ans_set and i not in val_oos_set
                ]
                val_ans_r = [rows[i] for i in val_ans_set]
                val_oos_r = [rows[i] for i in val_oos_set]

                chosen, _ = fit_preset(train_rows, floor=floor)
                params = {"t1": chosen[2], "t3": chosen[3], "k": chosen[4]}

                val_acc = sum(
                    1 for r in val_ans_r
                    if accept(float(r["s1_top1"]), float(r["s3_cov_top3"]),
                              float(r["s4_unknown"]), params)
                ) / len(val_ans_r)
                val_rej = sum(
                    1 for r in val_oos_r
                    if not accept(float(r["s1_top1"]), float(r["s3_cov_top3"]),
                                  float(r["s4_unknown"]), params)
                ) / len(val_oos_r)

                acc_list.append(val_acc)
                rej_list.append(val_rej)

        results[name] = {
            "acc_mean": float(np.mean(acc_list)),
            "acc_min": float(np.min(acc_list)),
            "rej_mean": float(np.mean(rej_list)),
            "rej_min": float(np.min(rej_list)),
        }
    return results


def load_old_presets():
    if os.path.exists(OLD_CONFIG_PATH):
        with open(OLD_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            name: {
                "t1": float(data[name]["t1"]),
                "t3": float(data[name]["t3"]),
                "k": int(data[name]["k"]),
            }
            for name in ("balanced", "strict")
        }
    return {k: dict(v) for k, v in OLD_PRESETS_FALLBACK.items()}


def evaluate_preset(rows, params):
    ans = [r for r in rows if r["answerable"]]
    oos = [r for r in rows if not r["answerable"]]
    accepted_ans = sum(
        1 for r in ans
        if accept(float(r["s1_top1"]), float(r["s3_cov_top3"]),
                  float(r["s4_unknown"]), params)
    )
    rejected_oos = sum(
        1 for r in oos
        if not accept(float(r["s1_top1"]), float(r["s3_cov_top3"]),
                      float(r["s4_unknown"]), params)
    )
    return accepted_ans, len(ans), rejected_oos, len(oos)


def find_interval(observed, threshold):
    vals = sorted(set(float(v) for v in observed))
    best = None
    for a, b in zip(vals, vals[1:]):
        mid = (a + b) / 2.0
        dist = abs(mid - threshold)
        if best is None or dist < best[0]:
            best = (dist, a, b, mid)
    return best


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else CSV_PATH
    fixes_path = sys.argv[2] if len(sys.argv) > 2 else FIXES_PATH

    print(f"Loading data from {csv_path} and {fixes_path}...")
    rows = load_labeled_signals(csv_path, fixes_path)

    ans_count = sum(1 for r in rows if r["answerable"])
    oos_count = sum(1 for r in rows if not r["answerable"])
    oos_by_cls = {}
    for r in rows:
        if not r["answerable"]:
            oos_by_cls[r["cls"]] = oos_by_cls.get(r["cls"], 0) + 1
    print(f"Total rows: {len(rows)} (Answerable: {ans_count}, OOS: {oos_count})")
    print(f"OOS class counts: {oos_by_cls}")
    assert ans_count == 63, f"expected 63 answerable rows, got {ans_count}"
    assert oos_count == 57, f"expected 57 out-of-scope rows, got {oos_count}"

    # Single-signal cuts (diagnostic only).
    ans_rows = [r for r in rows if r["answerable"]]
    oos_rows = [r for r in rows if not r["answerable"]]
    s1_ans = [float(r["s1_top1"]) for r in ans_rows]
    s1_oos = [float(r["s1_top1"]) for r in oos_rows]
    min_s1 = min(s1_ans)
    rej_min_s1 = sum(1 for x in s1_oos if x < min_s1)
    print(f"s1 100% answerable acceptance cut = {min_s1:.9f} -> rejects {rej_min_s1}/{len(oos_rows)}")

    sorted_s1_ans = sorted(s1_ans)
    s1_95_cut = sorted_s1_ans[3]
    rej_s1_95 = sum(1 for x in s1_oos if x < s1_95_cut)
    print(f"s1 95% answerable acceptance cut = {s1_95_cut:.9f} -> rejects {rej_s1_95}/{len(oos_rows)}")

    s3_ans = [float(r["s3_cov_top3"]) for r in ans_rows]
    s3_oos = [float(r["s3_cov_top3"]) for r in oos_rows]
    for val in sorted(set(s3_ans)):
        acc = sum(1 for x in s3_ans if x >= val) / len(s3_ans)
        rej = sum(1 for x in s3_oos if x < val)
        if 0.94 <= acc <= 0.96:
            print(f"s3 cut {val:.9f} (acc={acc:.4f}) -> rejects {rej}/{len(oos_rows)}")

    s4_ans = [float(r["s4_unknown"]) for r in ans_rows]
    s4_oos = [float(r["s4_unknown"]) for r in oos_rows]
    acc_s4_0 = sum(1 for x in s4_ans if x <= 0) / len(s4_ans)
    rej_s4_0 = sum(1 for x in s4_oos if x > 0)
    print(f"s4 <= 0 cut (acc={acc_s4_0:.4f}) -> rejects {rej_s4_0}/{len(oos_rows)}")

    print("\nThreshold candidates: midpoints between adjacent observed values "
          "(never equal to an observed value).")
    print(f"Comparison epsilon: {EPSILON:g}")

    bal_chosen, bal_tied = fit_preset(rows, floor=0.95)
    str_chosen, str_tied = fit_preset(rows, floor=0.90)

    bal_params = {"t1": bal_chosen[2], "t3": bal_chosen[3], "k": int(bal_chosen[4])}
    str_params = {"t1": str_chosen[2], "t3": str_chosen[3], "k": int(str_chosen[4])}

    observed_s1 = [float(r["s1_top1"]) for r in rows]
    observed_s3 = [float(r["s3_cov_top3"]) for r in rows]

    def rule_details(params):
        i1 = find_interval(observed_s1, params["t1"])
        i3 = find_interval(observed_s3, params["t3"])
        return {
            "t1_interval": [i1[1], i1[2]],
            "t1_midpoint": i1[3],
            "t3_interval": [i3[1], i3[2]],
            "t3_midpoint": i3[3],
            "t1_equals_observed": any(abs(params["t1"] - v) <= 1e-12 for v in observed_s1),
            "t3_equals_observed": any(abs(params["t3"] - v) <= 1e-12 for v in observed_s3),
        }

    bal_details = rule_details(bal_params)
    str_details = rule_details(str_params)

    print("\n=== FITTED PRESETS (K4b midpoints, epsilon applied) ===")
    for name, params, chosen, details in (
        ("balanced", bal_params, bal_chosen, bal_details),
        ("strict", str_params, str_chosen, str_details),
    ):
        accepted, total_ans, rejected, total_oos = evaluate_preset(rows, params)
        print(
            f"{name}: t1={params['t1']:.9f} t3={params['t3']:.9f} k={params['k']} "
            f"-> accepted {accepted}/{total_ans}, rejected {rejected}/{total_oos}"
        )
        print(
            f"  t1 midpoint of [{details['t1_interval'][0]:.9f}, "
            f"{details['t1_interval'][1]:.9f}]; "
            f"t3 midpoint of [{details['t3_interval'][0]:.9f}, "
            f"{details['t3_interval'][1]:.9f}]"
        )
        print(
            f"  never equal to observed: t1={not details['t1_equals_observed']}, "
            f"t3={not details['t3_equals_observed']}"
        )

    # Old presets evaluated on the new signals.
    old = load_old_presets()
    old_eval = {}
    print("\n=== OLD (PRE-K4b) PRESETS ON NEW DATA ===")
    for name, params in old.items():
        accepted, total_ans, rejected, total_oos = evaluate_preset(rows, params)
        old_eval[name] = {
            **params,
            "accepted_answerable": accepted,
            "total_answerable": total_ans,
            "rejected_oos": rejected,
            "total_oos": total_oos,
        }
        print(
            f"{name}: t1={params['t1']:.9f} t3={params['t3']:.9f} k={params['k']} "
            f"-> accepted {accepted}/{total_ans}, rejected {rejected}/{total_oos}"
        )

    # CV.
    print("\n=== 5-FOLD CV (30 repeats, seed 7) ===")
    cv_res = run_cv(rows)
    for name in ["balanced", "strict"]:
        r = cv_res[name]
        print(
            f"{name}: held-out acc mean={r['acc_mean']:.6f}, min={r['acc_min']:.6f} | "
            f"held-out rej mean={r['rej_mean']:.6f}, min={r['rej_min']:.6f}"
        )

    str_params["note"] = "sits on a slope; optional"

    # Write assets/gate_config.json.
    os.makedirs(os.path.dirname(CONFIG_OUT), exist_ok=True)
    gate_config = {
        "version": 1,
        "balanced": bal_params,
        "strict": str_params,
        "margin": 0.01,
    }
    with open(CONFIG_OUT, "w", encoding="utf-8") as f:
        json.dump(gate_config, f, indent=2)
        f.write("\n")
    print(f"\nWrote {CONFIG_OUT}")

    # Write assets/gate_reference.json.
    gate_ref = []
    for r in rows:
        s1 = float(r["s1_top1"])
        s2 = float(r["s2_margin"])
        s3 = float(r["s3_cov_top3"])
        s4 = float(r["s4_unknown"])
        s5 = float(r["s5_rare_cov_top3"])

        dec_bal = bool(accept(s1, s3, s4, bal_params))
        dec_str = bool(accept(s1, s3, s4, str_params))

        gate_ref.append({
            "group": r["group"],
            "cls": r["cls"],
            "id": int(r["id"]),
            "question": r["question"],
            "answerable": bool(r["answerable"]),
            "signals": {
                "s1_top1": s1,
                "s2_margin": s2,
                "s3_cov_top3": s3,
                "s4_unknown": s4,
                "s5_rare_cov_top3": s5,
            },
            "decisions": {
                "balanced": dec_bal,
                "strict": dec_str,
            }
        })

    with open(REFERENCE_OUT, "w", encoding="utf-8") as f:
        json.dump(gate_ref, f, indent=2)
        f.write("\n")
    print(f"Wrote {REFERENCE_OUT}")

    report = {
        "stage": "K4b",
        "epsilon": EPSILON,
        "candidate_rule": "midpoint between adjacent observed values; never equal to an observed value",
        "min_candidate_margin": MIN_CANDIDATE_MARGIN,
        "answerable": ans_count,
        "out_of_scope": oos_count,
        "oos_class_counts": oos_by_cls,
        "balanced": {
            **bal_params,
            **bal_details,
            "accepted_answerable": int(round(bal_chosen[1] * ans_count)),
            "total_answerable": ans_count,
            "rejected_oos": bal_chosen[0],
            "total_oos": oos_count,
            "tied_plateau_size": len(bal_tied),
        },
        "strict": {
            **str_params,
            **str_details,
            "accepted_answerable": int(round(str_chosen[1] * ans_count)),
            "total_answerable": ans_count,
            "rejected_oos": str_chosen[0],
            "total_oos": oos_count,
            "tied_plateau_size": len(str_tied),
        },
        "old_presets_on_new_data": old_eval,
        "cv": cv_res,
    }
    # Use the exact re-evaluated counts (epsilon applied) rather than the
    # rounded search value.
    for name, params in (("balanced", bal_params), ("strict", str_params)):
        accepted, total_ans, rejected, total_oos = evaluate_preset(rows, params)
        report[name]["accepted_answerable"] = accepted
        report[name]["rejected_oos"] = rejected
    os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(f"Wrote {REPORT_OUT}")

    # Print in full: rejected answerable and accepted OOS.
    for preset_name, params in [("balanced", bal_params), ("strict", str_params)]:
        rej_ans = []
        acc_oos = []
        for r in rows:
            s1 = float(r["s1_top1"])
            s3 = float(r["s3_cov_top3"])
            s4 = float(r["s4_unknown"])
            if accept(s1, s3, s4, params):
                if not r["answerable"]:
                    acc_oos.append(r)
            elif r["answerable"]:
                rej_ans.append(r)

        print("\n==========================================")
        print(f"PRESET: {preset_name.upper()} (t1={params['t1']:.9f}, t3={params['t3']:.9f}, k={params['k']})")
        print(f"Answerable rejected: {len(rej_ans)}/{ans_count}")
        for r in rej_ans:
            print(
                f"  [REJECTED ANS] id={r['id']} cls={r['cls']} "
                f"s1={float(r['s1_top1']):.9f} s3={float(r['s3_cov_top3']):.9f} "
                f"s4={float(r['s4_unknown']):.1f} | {r['question']}"
            )
        print(f"Out-of-scope accepted: {len(acc_oos)}/{oos_count}")
        for r in acc_oos:
            print(
                f"  [ACCEPTED OOS] id={r['id']} cls={r['cls']} "
                f"s1={float(r['s1_top1']):.9f} s3={float(r['s3_cov_top3']):.9f} "
                f"s4={float(r['s4_unknown']):.1f} | {r['question']}"
            )


if __name__ == "__main__":
    main()
