#!/usr/bin/env python3
"""K4c report driver: sensitivity, robust fit, cross-runner evaluation, CV.

This script is meant to be run against the CI artifacts, not against the local
Cortex-A55 signals:

  python3 scripts/k4c_analysis.py \
    --csv /tmp/opencode/k4b_run1/gate-signals-csv/gate_signals.csv \
    --cross-csv /tmp/opencode/k4b_run2/gate-signals-csv/gate_signals.csv \
    --k4b-report /tmp/opencode/k4b_run1/k4b-reports/build/reports/k4b/gate_refit_report.json

Every number in the K4c report is produced by this run (or by CI logs).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fit_gate
import robust_gate

FLOORS = (("balanced", 0.90), ("strict", 0.85))


def load_k4b_presets(path):
    """Return the K4b presets as fitted on the primary CSV."""
    with open(path, "r", encoding="utf-8") as f:
        report = json.load(f)
    return {
        "K4b balanced": {
            "t1": float(report["balanced"]["t1"]),
            "t3": float(report["balanced"]["t3"]),
            "k": int(report["balanced"]["k"]),
        },
        "K4b strict": {
            "t1": float(report["strict"]["t1"]),
            "t3": float(report["strict"]["t3"]),
            "k": int(report["strict"]["k"]),
        },
    }


def evaluate(rows, params):
    accepted, total_ans, rejected, total_oos = fit_gate.evaluate_preset(rows, params)
    return {
        "accepted_answerable": accepted,
        "total_answerable": total_ans,
        "rejected_oos": rejected,
        "total_oos": total_oos,
    }


def evaluate_worst(rows, params):
    worst_acc = None
    worst_rej = None
    per_delta = []
    for d in robust_gate.FIT_DELTAS:
        accepted, total_ans, rejected, total_oos = robust_gate.evaluate_shift(
            rows, params, d
        )
        per_delta.append(
            {
                "d": d,
                "accepted_answerable": accepted,
                "rejected_oos": rejected,
            }
        )
        if worst_acc is None or accepted < worst_acc:
            worst_acc = accepted
        if worst_rej is None or rejected < worst_rej:
            worst_rej = rejected
    return {
        "worst_accepted_answerable": worst_acc,
        "worst_rejected_oos": worst_rej,
        "total_answerable": total_ans,
        "total_oos": total_oos,
        "per_delta": per_delta,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=fit_gate.CSV_PATH)
    parser.add_argument("--cross-csv", default=None)
    parser.add_argument("--k4b-report", default=None)
    parser.add_argument("--fixes", default=fit_gate.FIXES_PATH)
    parser.add_argument(
        "--out",
        default=os.path.join("build", "reports", "k4c", "k4c_analysis.json"),
    )
    args = parser.parse_args()

    rows = fit_gate.load_labeled_signals(args.csv, args.fixes)
    cross_rows = (
        fit_gate.load_labeled_signals(args.cross_csv, args.fixes)
        if args.cross_csv
        else None
    )

    k3_presets = fit_gate.load_old_presets()
    sensitivity_presets = {}
    if args.k4b_report:
        sensitivity_presets.update(load_k4b_presets(args.k4b_report))
    sensitivity_presets["K3 balanced"] = k3_presets["balanced"]
    sensitivity_presets["K3 strict"] = k3_presets["strict"]

    # 1. Sensitivity table on the primary CSV.
    sensitivity = robust_gate.sensitivity(rows, sensitivity_presets)

    # 2. Robust fit on the primary CSV.
    candidates = robust_gate.build_candidates(rows)
    fitted = {}
    for name, floor in FLOORS:
        chosen, tied, plateau = robust_gate.select_preset(candidates, floor)
        top = robust_gate.top_candidates(candidates, floor, limit=5)
        fitted[name] = {
            "floor": floor,
            "chosen": {
                "t1": chosen.t1,
                "t3": chosen.t3,
                "k": chosen.k,
                "worst_acc_count": chosen.worst_acc_count,
                "worst_rej_count": chosen.worst_rej_count,
                "worst_acc": chosen.worst_acc,
                "worst_rej": chosen.worst_rej,
                "nominal_acc_count": chosen.nominal_acc_count,
                "nominal_rej_count": chosen.nominal_rej_count,
                "per_delta": [
                    {"d": d, "accepted_answerable": a, "rejected_oos": r}
                    for d, a, r in chosen.per_delta
                ],
            },
            "plateau": plateau,
            "top5": [
                {
                    "t1": c.t1,
                    "t3": c.t3,
                    "k": c.k,
                    "worst_acc_count": c.worst_acc_count,
                    "worst_rej_count": c.worst_rej_count,
                    "worst_acc": c.worst_acc,
                    "worst_rej": c.worst_rej,
                    "nominal_acc_count": c.nominal_acc_count,
                    "nominal_rej_count": c.nominal_rej_count,
                }
                for c in top
            ],
        }

    # 3. Cross-runner evaluation and repeated CV.
    k4c_presets = {
        "K4c balanced": {
            "t1": fitted["balanced"]["chosen"]["t1"],
            "t3": fitted["balanced"]["chosen"]["t3"],
            "k": fitted["balanced"]["chosen"]["k"],
        },
        "K4c strict": {
            "t1": fitted["strict"]["chosen"]["t1"],
            "t3": fitted["strict"]["chosen"]["t3"],
            "k": fitted["strict"]["chosen"]["k"],
        },
    }
    presets = {}
    if args.k4b_report:
        presets.update(load_k4b_presets(args.k4b_report))
    presets.update(k4c_presets)

    comparison = {}
    for name, params in presets.items():
        comparison[name] = {
            "params": params,
            "run1_nominal": evaluate(rows, params),
            "run1_worst": evaluate_worst(rows, params),
            "run2_nominal": evaluate(cross_rows, params) if cross_rows else None,
            "run2_worst": evaluate_worst(cross_rows, params) if cross_rows else None,
        }

    cv = {"run1": robust_gate.run_cv(rows, FLOORS)}
    if cross_rows is not None:
        cv["run2"] = robust_gate.run_cv(cross_rows, FLOORS)

    result = {
        "stage": "K4c",
        "primary_csv": args.csv,
        "cross_csv": args.cross_csv,
        "k4b_report": args.k4b_report,
        "sensitivity_presets": sensitivity_presets,
        "sensitivity": sensitivity,
        "fit": fitted,
        "comparison": comparison,
        "cv": cv,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    # Console tables, in a copy-friendly form.
    deltas = [item["d"] for item in next(iter(sensitivity.values()))]
    print("\n## 1. Sensitivity (answerable accepted /63, OOS rejected /57)")
    print("| preset | " + " | ".join(f"d={d:+.4f}" for d in deltas) + " |")
    print("|" + "---|" * (len(deltas) + 1))
    for name, items in sensitivity.items():
        cells = [
            f"{i['accepted_answerable']}/63, {i['rejected_oos']}/57" for i in items
        ]
        print(f"| {name} | " + " | ".join(cells) + " |")

    for key in ("balanced", "strict"):
        f = fitted[key]
        c = f["chosen"]
        p = f["plateau"]
        print(f"\n## 2. Robust fit: {key} (worst-case acceptance >= {f['floor']:.2f})")
        print(
            f"chosen t1={c['t1']:.9f} t3={c['t3']:.9f} k={c['k']} | "
            f"worst {c['worst_acc_count']}/63 ({c['worst_acc']:.6f}), "
            f"{c['worst_rej_count']}/57 ({c['worst_rej']:.6f}) | "
            f"nominal {c['nominal_acc_count']}/63, {c['nominal_rej_count']}/57"
        )
        print(
            f"plateau t1 [{p['t1_min']:.9f}, {p['t1_max']:.9f}] "
            f"width {p['t1_width']:.9f} centre {p['t1_centre']:.9f}; "
            f"t3 [{p['t3_min']:.9f}, {p['t3_max']:.9f}] width {p['t3_width']:.9f}; "
            f"tied {p['tied_count']}"
        )
        print(
            "| rank | t1 | t3 | k | worst acc | worst rej | nominal acc | nominal rej |"
        )
        print("|---|---|---|---|---|---|---|---|")
        for rank, item in enumerate(f["top5"], 1):
            print(
                f"| {rank} | {item['t1']:.9f} | {item['t3']:.9f} | {item['k']} | "
                f"{item['worst_acc_count']}/63 ({item['worst_acc']:.6f}) | "
                f"{item['worst_rej_count']}/57 ({item['worst_rej']:.6f}) | "
                f"{item['nominal_acc_count']}/63 | {item['nominal_rej_count']}/57 |"
            )

    print("\n## 3a. Fixed presets on both CPU CSVs (nominal and worst-case d in {-0.005,0,+0.005})")
    print(
        "| preset | t1 | t3 | k | run1 acc | run1 rej | run1 worst acc | run1 worst rej | "
        "run2 acc | run2 rej | run2 worst acc | run2 worst rej |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, ev in comparison.items():
        params = ev["params"]
        r1 = ev["run1_nominal"]
        r1w = ev["run1_worst"]
        r2 = ev["run2_nominal"]
        r2w = ev["run2_worst"]

        def cell_nominal(x):
            return (
                f"{x['accepted_answerable']}/63 | {x['rejected_oos']}/57"
                if x
                else "n/a | n/a"
            )

        def cell_worst(x):
            return (
                f"{x['worst_accepted_answerable']}/63 | {x['worst_rejected_oos']}/57"
                if x
                else "n/a | n/a"
            )

        print(
            f"| {name} | {params['t1']:.9f} | {params['t3']:.9f} | {params['k']} | "
            f"{cell_nominal(r1)} | {cell_worst(r1w)} | "
            f"{cell_nominal(r2)} | {cell_worst(r2w)} |"
        )

    print("\n## 3b. Repeated 5-fold CV, robust refit per fold (30 repeats, seed 7)")
    print(
        "| preset | run1 acc mean/min | run1 rej mean/min | "
        "run1 worst acc mean/min | run1 worst rej mean/min | "
        "run2 acc mean/min | run2 rej mean/min | "
        "run2 worst acc mean/min | run2 worst rej mean/min |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for key in ("balanced", "strict"):
        c1 = cv["run1"][key]
        c2 = cv["run2"][key] if cv.get("run2") else None

        def pair(mean_key, min_key, block):
            return f"{block[mean_key]:.6f}/{block[min_key]:.6f}"

        print(
            f"| K4c {key} | {pair('acc_mean', 'acc_min', c1)} | "
            f"{pair('rej_mean', 'rej_min', c1)} | "
            f"{pair('worst_acc_mean', 'worst_acc_min', c1)} | "
            f"{pair('worst_rej_mean', 'worst_rej_min', c1)} | "
            + (
                f"{pair('acc_mean', 'acc_min', c2)} | "
                f"{pair('rej_mean', 'rej_min', c2)} | "
                f"{pair('worst_acc_mean', 'worst_acc_min', c2)} | "
                f"{pair('worst_rej_mean', 'worst_rej_min', c2)} |"
                if c2
                else "n/a | n/a | n/a | n/a |"
            )
        )

    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
