#!/usr/bin/env python3
"""K4c: verify robust grid thresholds, IN 14 (s3 = 4/7), and Kotlin parity.

Runs after ``scripts/measure_gate_signals.py`` (which calls ``fit_gate.py``)
and after the Kotlin JVM tests.  Every number is read back from a file produced
by those steps, not retyped.

Checks
------
1. Fitted t1 values lie on the 0.82..0.88 / 0.0025 grid; t3 values are observed
   s3 values; k is in 0..3.  The config also matches the K4c fit report.
2. Question IN 14 has s3 = 4/7, and Python and Kotlin take the same decision
   for both presets.
3. Kotlin s3/s4 parity is 120/120.
4. max |s1_python - s1_kotlin| <= 1e-4 over all 120 questions.
5. Balanced and strict decisions agree 120/120; every disagreement is listed
   with s1, t1, s3, t3 and a reason.

Output: build/reports/k4c/k4c_verification.json
"""
from __future__ import annotations

import csv
import json
import os
import sys

CONFIG = os.path.join("app", "src", "main", "assets", "gate_config.json")
FIT_REPORT = os.path.join("build", "reports", "k4c", "robust_fit_report.json")
SIGNALS = os.path.join("eval", "gate_signals.csv")
STEMS_CSV = os.path.join("build", "reports", "parity", "gate_stems_parity.csv")
DECISIONS_CSV = os.path.join("build", "reports", "parity", "gate_decisions.csv")
OUT_JSON = os.path.join("build", "reports", "k4c", "k4c_verification.json")

S1_EPS = 1e-4
MIN_DECISION_MATCHES = 120
T1_START = 0.82
T1_STEP = 0.0025


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def verify_grid_thresholds(config, signals, fit_report):
    observed_s3 = sorted(set(float(r["s3_cov_top3"]) for r in signals))
    checks = {}
    for preset in ("balanced", "strict"):
        t1 = float(config[preset]["t1"])
        t3 = float(config[preset]["t3"])
        k = int(config[preset]["k"])
        grid_index = (t1 - T1_START) / T1_STEP
        nearest = round(grid_index)
        t1_on_grid = abs(grid_index - nearest) <= 1e-9 and 0 <= nearest <= 24
        t3_dist = min(abs(t3 - v) for v in observed_s3) if observed_s3 else None
        t3_observed = t3_dist is not None and t3_dist <= 1e-9
        report_match = None
        if fit_report is not None:
            selected = fit_report.get("selected", {}).get(preset, {})
            report_match = (
                abs(float(selected.get("t1", float("nan"))) - t1) <= 1e-12
                and abs(float(selected.get("t3", float("nan"))) - t3) <= 1e-12
                and int(selected.get("k", -1)) == k
            )
        checks[preset] = {
            "t1": t1,
            "t1_grid_index": grid_index,
            "t1_on_grid": t1_on_grid,
            "t3": t3,
            "t3_observed_distance": t3_dist,
            "t3_is_observed": t3_observed,
            "k": k,
            "k_in_range": k in (0, 1, 2, 3),
            "fit_report_match": report_match,
            "ok": t1_on_grid and t3_observed and k in (0, 1, 2, 3)
            and (report_match is not False),
        }
    return checks


def main() -> int:
    required = [CONFIG, SIGNALS, STEMS_CSV, DECISIONS_CSV]
    for path in required:
        if not os.path.exists(path):
            print(f"ERROR: missing {path}", file=sys.stderr)
            return 1

    with open(CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)
    fit_report = None
    if os.path.exists(FIT_REPORT):
        with open(FIT_REPORT, "r", encoding="utf-8") as f:
            fit_report = json.load(f)

    signals = read_csv(SIGNALS)
    if len(signals) != 120:
        print(f"ERROR: expected 120 signal rows, got {len(signals)}", file=sys.stderr)
        return 1

    checks = {}

    # 1. Robust grid thresholds.
    checks["thresholds"] = verify_grid_thresholds(config, signals, fit_report)

    # 2. IN 14: s3 = 4/7 and Kotlin/Python decisions.
    in14 = next(
        (r for r in signals if r["group"] == "in" and int(r["id"]) == 14),
        None,
    )
    if in14 is None:
        print("ERROR: IN 14 missing from gate_signals.csv", file=sys.stderr)
        return 1
    s3_python = float(in14["s3_cov_top3"])
    four_sevenths = 4.0 / 7.0
    decision_rows = [
        r for r in read_csv(DECISIONS_CSV)
        if r.get("cls") == "IN" and int(r.get("id", -1)) == 14
    ]
    in14_decisions = {
        r["preset"]: {
            "python_decision": r["python_decision"],
            "kotlin_decision": r["kotlin_decision"],
            "agree": r["agree"] == "YES",
            "s1_python": float(r["s1_python"]),
            "s1_kotlin": float(r["s1_kotlin"]),
            "s3_kotlin": float(r["s3_kotlin"]),
            "t1": float(r["t1"]),
            "t3": float(r["t3"]),
        }
        for r in decision_rows
    }
    checks["in14"] = {
        "s3_python": s3_python,
        "s3_four_sevenths": four_sevenths,
        "abs_diff": abs(s3_python - four_sevenths),
        "is_four_sevenths": abs(s3_python - four_sevenths) <= 5e-9,
        "decisions": in14_decisions,
        "both_presets_agree": all(v["agree"] for v in in14_decisions.values())
        and len(in14_decisions) == 2,
    }

    # 3. s3/s4 parity.
    stems = read_csv(STEMS_CSV)
    s3_matches = sum(1 for r in stems if r.get("s3_match") == "YES")
    s4_matches = sum(1 for r in stems if r.get("s4_match") == "YES")
    checks["stems_parity"] = {
        "total": len(stems),
        "s3_matches": s3_matches,
        "s4_matches": s4_matches,
        "ok": len(stems) == 120 and s3_matches == 120 and s4_matches == 120,
    }

    # 4. s1 delta (deduplicate by cls/id; each preset repeats the same row).
    decisions = read_csv(DECISIONS_CSV)
    seen = {}
    for r in decisions:
        key = (r.get("cls"), int(r.get("id", -1)))
        if key not in seen:
            seen[key] = abs(float(r["s1_python"]) - float(r["s1_kotlin"]))
    deltas = list(seen.values())
    checks["s1_delta"] = {
        "rows": len(deltas),
        "max_abs_delta": max(deltas) if deltas else None,
        "mean_abs_delta": (sum(deltas) / len(deltas)) if deltas else None,
        "threshold": S1_EPS,
        "ok": bool(deltas) and max(deltas) <= S1_EPS,
    }

    # 5. Decisions per preset (must be 120/120 for K4c).
    decision_summary = {}
    for preset in ("balanced", "strict"):
        rows = [r for r in decisions if r.get("preset") == preset]
        disagreements = []
        for r in rows:
            if r.get("agree") != "YES":
                disagreements.append({
                    "preset": preset,
                    "cls": r.get("cls"),
                    "id": int(r.get("id", -1)),
                    "question": r.get("question"),
                    "python_decision": r.get("python_decision"),
                    "kotlin_decision": r.get("kotlin_decision"),
                    "s1_python": float(r.get("s1_python", "nan")),
                    "s1_kotlin": float(r.get("s1_kotlin", "nan")),
                    "t1": float(r.get("t1", "nan")),
                    "s3_python": float(r.get("s3_python", "nan")),
                    "s3_kotlin": float(r.get("s3_kotlin", "nan")),
                    "t3": float(r.get("t3", "nan")),
                    "reason": r.get("reason"),
                })
        matches = len(rows) - len(disagreements)
        ok = len(rows) == 120 and matches >= MIN_DECISION_MATCHES
        decision_summary[preset] = {
            "total": len(rows),
            "matches": matches,
            "required": MIN_DECISION_MATCHES,
            "ok": ok,
            "disagreements": disagreements,
        }
    checks["decisions"] = decision_summary

    thresholds_ok = all(v["ok"] for v in checks["thresholds"].values())
    overall = (
        thresholds_ok
        and checks["in14"]["is_four_sevenths"]
        and checks["in14"]["both_presets_agree"]
        and checks["stems_parity"]["ok"]
        and checks["s1_delta"]["ok"]
        and all(v["ok"] for v in decision_summary.values())
    )
    result = {"stage": "K4c", "pass": overall, "checks": checks}

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    print("=== K4c verification ===")
    for preset, c in checks["thresholds"].items():
        print(
            f"{preset}: t1={c['t1']:.9f} grid_index={c['t1_grid_index']:.3f} "
            f"on_grid={c['t1_on_grid']} | t3={c['t3']:.9f} "
            f"observed_dist={c['t3_observed_distance']:.3e} "
            f"is_observed={c['t3_is_observed']} | k={c['k']} "
            f"report_match={c['fit_report_match']} OK={c['ok']}"
        )
    i14 = checks["in14"]
    print(
        f"IN 14: s3_python={i14['s3_python']:.9f}, 4/7={i14['s3_four_sevenths']:.9f}, "
        f"abs_diff={i14['abs_diff']:.3e}, is_4/7={i14['is_four_sevenths']}, "
        f"both_presets_agree={i14['both_presets_agree']}"
    )
    for preset, v in i14["decisions"].items():
        print(
            f"  IN14 {preset}: python={v['python_decision']} kotlin={v['kotlin_decision']} "
            f"agree={v['agree']} s1_python={v['s1_python']:.9f} s1_kotlin={v['s1_kotlin']:.9f} "
            f"t1={v['t1']:.9f} s3_kotlin={v['s3_kotlin']:.9f} t3={v['t3']:.9f}"
        )
    sp = checks["stems_parity"]
    print(f"Kotlin s3/s4 parity: s3 {sp['s3_matches']}/{sp['total']}, s4 {sp['s4_matches']}/{sp['total']}")
    sd = checks["s1_delta"]
    print(
        f"|s1_python - s1_kotlin|: max={sd['max_abs_delta']:.3e} mean={sd['mean_abs_delta']:.3e} "
        f"over {sd['rows']} questions (threshold {sd['threshold']:g})"
    )
    for preset, v in decision_summary.items():
        print(f"{preset} decisions: {v['matches']}/{v['total']} equal (required {v['required']})")
        for d in v["disagreements"]:
            print(
                f"  DISAGREE {preset} {d['cls']} id={d['id']} s1={d['s1_kotlin']:.9f} "
                f"t1={d['t1']:.9f} s3={d['s3_kotlin']:.9f} t3={d['t3']:.9f} | {d['reason']}"
            )
    print(f"Wrote {OUT_JSON}")
    print(f"K4c verification overall: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
