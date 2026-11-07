#!/usr/bin/env python3
"""K4b: verify the midpoint thresholds, IN 14 (s3 = 4/7), and Kotlin parity.

Runs after ``scripts/measure_gate_signals.py`` (which calls ``fit_gate.py``)
and after the Kotlin JVM tests.  Every number is read back from a file produced
by those steps, not retyped.

Checks
------
1. Every fitted t1/t3 is the midpoint of two adjacent observed signal values
   and is not equal to any observed value.
2. Question IN 14 has s3 = 4/7, and Python and Kotlin take the same decision
   for both presets.
3. Kotlin s3/s4 parity is 120/120.
4. max |s1_python - s1_kotlin| <= 1e-4 over all 120 questions.
5. Balanced and strict decisions agree on at least 119/120 questions; every
   disagreement is listed with s1, t1, s3, t3 and a reason.

Output: build/reports/k4b/k4b_verification.json
"""
from __future__ import annotations

import csv
import json
import os
import sys

CONFIG = os.path.join("app", "src", "main", "assets", "gate_config.json")
SIGNALS = os.path.join("eval", "gate_signals.csv")
STEMS_CSV = os.path.join("build", "reports", "parity", "gate_stems_parity.csv")
DECISIONS_CSV = os.path.join("build", "reports", "parity", "gate_decisions.csv")
OUT_JSON = os.path.join("build", "reports", "k4b", "k4b_verification.json")

S1_EPS = 1e-4
MIN_DECISION_MATCHES = 119


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def observed_values(rows, field):
    return sorted(set(float(r[field]) for r in rows))


def midpoint_interval(observed, threshold):
    best = None
    for a, b in zip(observed, observed[1:]):
        mid = (a + b) / 2.0
        dist = abs(mid - threshold)
        if best is None or dist < best[0]:
            best = (dist, a, b, mid)
    return best


def verify_threshold(rows, field, threshold):
    observed = observed_values(rows, field)
    best = midpoint_interval(observed, threshold)
    if best is None:
        return {"ok": False, "reason": "fewer than two observed values"}
    dist, lo, hi, mid = best
    equals_observed = any(abs(threshold - v) <= 1e-12 for v in observed)
    return {
        "ok": (dist <= 1e-9) and (not equals_observed),
        "threshold": threshold,
        "observed_below": lo,
        "observed_above": hi,
        "midpoint": mid,
        "midpoint_error": dist,
        "equals_observed": equals_observed,
        "observed_unique": len(observed),
    }


def main() -> int:
    for path in (CONFIG, SIGNALS, STEMS_CSV, DECISIONS_CSV):
        if not os.path.exists(path):
            print(f"ERROR: missing {path}", file=sys.stderr)
            return 1

    with open(CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)

    signals = read_csv(SIGNALS)
    if len(signals) != 120:
        print(f"ERROR: expected 120 signal rows, got {len(signals)}", file=sys.stderr)
        return 1

    checks = {}

    # 1. Midpoint thresholds.
    checks["balanced_t1"] = verify_threshold(signals, "s1_top1", float(config["balanced"]["t1"]))
    checks["balanced_t3"] = verify_threshold(signals, "s3_cov_top3", float(config["balanced"]["t3"]))
    checks["strict_t1"] = verify_threshold(signals, "s1_top1", float(config["strict"]["t1"]))
    checks["strict_t3"] = verify_threshold(signals, "s3_cov_top3", float(config["strict"]["t3"]))

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

    # 5. Decisions per preset.
    decision_summary = {}
    all_ok = True
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
        all_ok = all_ok and ok
        decision_summary[preset] = {
            "total": len(rows),
            "matches": matches,
            "required": MIN_DECISION_MATCHES,
            "ok": ok,
            "disagreements": disagreements,
        }
    checks["decisions"] = decision_summary

    midpoint_ok = all(
        checks[key]["ok"]
        for key in ("balanced_t1", "balanced_t3", "strict_t1", "strict_t3")
    )
    overall = (
        midpoint_ok
        and checks["in14"]["is_four_sevenths"]
        and checks["in14"]["both_presets_agree"]
        and checks["stems_parity"]["ok"]
        and checks["s1_delta"]["ok"]
        and all(v["ok"] for v in decision_summary.values())
    )
    result = {"stage": "K4b", "pass": overall, "checks": checks}

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    print("=== K4b verification ===")
    for key in ("balanced_t1", "balanced_t3", "strict_t1", "strict_t3"):
        c = checks[key]
        print(
            f"{key}: threshold={c.get('threshold')} midpoint=[{c.get('observed_below')}, "
            f"{c.get('observed_above')}] -> {c.get('midpoint')} "
            f"(error={c.get('midpoint_error'):.3e}, equals_observed={c.get('equals_observed')}) "
            f"OK={c.get('ok')}"
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
        print(f"{preset} decisions: {v['matches']}/{v['total']} equal (required >= {v['required']})")
        for d in v["disagreements"]:
            print(
                f"  DISAGREE {preset} {d['cls']} id={d['id']} s1={d['s1_kotlin']:.9f} "
                f"t1={d['t1']:.9f} s3={d['s3_kotlin']:.9f} t3={d['t3']:.9f} | {d['reason']}"
            )
    print(f"Wrote {OUT_JSON}")
    print(f"K4b verification overall: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
