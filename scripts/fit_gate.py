#!/usr/bin/env python3
"""Stage K4c: fit robust refusal-gate presets and write the app assets.

Reads eval/gate_signals.csv and eval/label_fixes.json.

K4c changes
-----------
* Candidates are the t1 grid 0.82..0.88 step 0.0025, the observed s3 values,
  and k in 0..3.
* Each candidate is scored by its worst case over s1 shifts
  d in (-0.005, 0, +0.005).
* balanced: maximise worst-case OOS rejection with worst-case answerable
  acceptance >= 0.90.
* strict:   maximise worst-case OOS rejection with worst-case answerable
  acceptance >= 0.85.
* Ties pick the t1 centre of the tied plateau (see robust_gate.py).
* The 1e-6 comparison epsilon from gate_rule.py is kept.

Outputs:
  app/src/main/assets/gate_config.json
  app/src/main/assets/gate_reference.json
  build/reports/k4c/robust_fit_report.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import robust_gate
from gate_rule import EPSILON, accept

CSV_PATH = os.path.join("eval", "gate_signals.csv")
FIXES_PATH = os.path.join("eval", "label_fixes.json")
OLD_CONFIG_PATH = os.path.join("eval", "gate_config_old.json")
CONFIG_OUT = os.path.join("app", "src", "main", "assets", "gate_config.json")
REFERENCE_OUT = os.path.join("app", "src", "main", "assets", "gate_reference.json")
REPORT_OUT = os.path.join("build", "reports", "k4c", "robust_fit_report.json")

FLOORS = (("balanced", 0.90), ("strict", 0.85))

# Pre-K3 presets, used only when eval/gate_config_old.json is absent.
OLD_PRESETS_FALLBACK = {
    "balanced": {"t1": 0.8375, "t3": 0.571429, "k": 0},
    "strict": {"t1": 0.8525, "t3": 0.571429, "k": 0},
}


def load_labeled_signals(csv_path=CSV_PATH, fixes_path=FIXES_PATH):
    fixes_by_id = set()
    if os.path.exists(fixes_path):
        with open(fixes_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for fix in data.get("fixes", []):
                if fix.get("action") == "answered_by_book":
                    fixes_by_id.add(int(fix["id"]))

    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(__import__("csv").DictReader(f))

    for r in rows:
        cid = int(r["id"])
        cls = r["cls"]
        if cls == "IN" or (cls == "B" and cid in fixes_by_id):
            r["answerable"] = True
        else:
            r["answerable"] = False

    return rows


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
        1
        for r in ans
        if accept(
            float(r["s1_top1"]),
            float(r["s3_cov_top3"]),
            float(r["s4_unknown"]),
            params,
        )
    )
    rejected_oos = sum(
        1
        for r in oos
        if not accept(
            float(r["s1_top1"]),
            float(r["s3_cov_top3"]),
            float(r["s4_unknown"]),
            params,
        )
    )
    return accepted_ans, len(ans), rejected_oos, len(oos)


def fit_preset(rows, floor):
    """Compatibility wrapper returning ``(chosen, tied)`` tuples."""
    return robust_gate.fit_preset(rows, floor)


def candidate_json(candidate):
    return {
        "t1": candidate.t1,
        "t3": candidate.t3,
        "k": candidate.k,
        "worst_acc_count": candidate.worst_acc_count,
        "worst_rej_count": candidate.worst_rej_count,
        "worst_acc": candidate.worst_acc,
        "worst_rej": candidate.worst_rej,
        "nominal_acc_count": candidate.nominal_acc_count,
        "nominal_rej_count": candidate.nominal_rej_count,
        "nominal_acc": candidate.nominal_acc,
        "nominal_rej": candidate.nominal_rej,
        "per_delta": [
            {"d": d, "accepted_answerable": a, "rejected_oos": r}
            for d, a, r in candidate.per_delta
        ],
    }


def plateau_json(plateau):
    return {
        "tied_count": plateau["tied_count"],
        "t1_min": plateau["t1_min"],
        "t1_max": plateau["t1_max"],
        "t1_width": plateau["t1_width"],
        "t1_centre": plateau["t1_centre"],
        "t1_unique": plateau["t1_unique"],
        "t3_min": plateau["t3_min"],
        "t3_max": plateau["t3_max"],
        "t3_width": plateau["t3_width"],
        "t3_unique": plateau["t3_unique"],
        "worst_rej_count": plateau["worst_rej_count"],
    }


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

    print("\nK4c robust fit")
    print(f"  t1 grid: {robust_gate.T1_START}..{robust_gate.T1_END} "
          f"step {robust_gate.T1_STEP}")
    print(f"  t3 grid: {len(robust_gate.observed_s3(rows))} observed s3 values")
    print(f"  k grid: {list(robust_gate.K_GRID)}")
    print(f"  shift set: {list(robust_gate.FIT_DELTAS)}")
    print(f"  comparison epsilon: {EPSILON:g}")

    candidates = robust_gate.build_candidates(rows)
    print(f"  candidates evaluated: {len(candidates)}")

    selected = {}
    report_presets = {}
    for name, floor in FLOORS:
        chosen, tied, plateau = robust_gate.select_preset(candidates, floor)
        selected[name] = {
            "t1": chosen.t1,
            "t3": chosen.t3,
            "k": chosen.k,
        }
        top = robust_gate.top_candidates(candidates, floor, limit=5)
        report_presets[name] = {
            "floor": floor,
            **candidate_json(chosen),
            "plateau": plateau_json(plateau),
            "top5": [candidate_json(c) for c in top],
        }
        print(f"\n=== {name.upper()} (worst-case acceptance >= {floor:.2f}) ===")
        print(
            f"chosen: t1={chosen.t1:.9f} t3={chosen.t3:.9f} k={chosen.k} | "
            f"worst acc={chosen.worst_acc_count}/{chosen.n_answerable} "
            f"({chosen.worst_acc:.6f}), "
            f"worst rej={chosen.worst_rej_count}/{chosen.n_oos} "
            f"({chosen.worst_rej:.6f}) | "
            f"nominal acc={chosen.nominal_acc_count}/{chosen.n_answerable}, "
            f"nominal rej={chosen.nominal_rej_count}/{chosen.n_oos}"
        )
        print(
            f"plateau: t1 [{plateau['t1_min']:.9f}, {plateau['t1_max']:.9f}] "
            f"width={plateau['t1_width']:.9f} (centre {plateau['t1_centre']:.9f}), "
            f"t3 [{plateau['t3_min']:.9f}, {plateau['t3_max']:.9f}] "
            f"width={plateau['t3_width']:.9f}, tied={plateau['tied_count']}"
        )
        for d, a, r in chosen.per_delta:
            print(
                f"  d={d:+.4f}: accepted {a}/{chosen.n_answerable}, "
                f"rejected {r}/{chosen.n_oos}"
            )
        print("  top 5 candidates:")
        for rank, c in enumerate(top, 1):
            print(
                f"    {rank}. t1={c.t1:.9f} t3={c.t3:.9f} k={c.k} | "
                f"worst acc={c.worst_acc_count}/{c.n_answerable} "
                f"({c.worst_acc:.6f}), "
                f"worst rej={c.worst_rej_count}/{c.n_oos} "
                f"({c.worst_rej:.6f}) | "
                f"nominal acc={c.nominal_acc_count}/{c.n_answerable}, "
                f"nominal rej={c.nominal_rej_count}/{c.n_oos}"
            )

    # Old K3 presets evaluated on the same signals.
    old = load_old_presets()
    old_eval = {}
    print("\n=== OLD (K3) PRESETS ON THE SAME SIGNALS ===")
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

    # Repeated 5-fold CV with robust refitting.
    print("\n=== 5-FOLD CV (30 repeats, seed 7, robust refit) ===")
    cv_res = robust_gate.run_cv(rows, FLOORS)
    for name, _ in FLOORS:
        r = cv_res[name]
        print(
            f"{name}: nominal held-out acc mean={r['acc_mean']:.6f}, min={r['acc_min']:.6f} | "
            f"rej mean={r['rej_mean']:.6f}, min={r['rej_min']:.6f}"
        )
        print(
            f"  worst-case (d in {list(robust_gate.FIT_DELTAS)}): "
            f"acc mean={r['worst_acc_mean']:.6f}, min={r['worst_acc_min']:.6f} | "
            f"rej mean={r['worst_rej_mean']:.6f}, min={r['worst_rej_min']:.6f}"
        )

    bal_params = dict(selected["balanced"])
    str_params = dict(selected["strict"])
    str_params["note"] = "robust K4c preset; optional"

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
                "balanced": bool(accept(s1, s3, s4, bal_params)),
                "strict": bool(accept(s1, s3, s4, str_params)),
            },
        })

    with open(REFERENCE_OUT, "w", encoding="utf-8") as f:
        json.dump(gate_ref, f, indent=2)
        f.write("\n")
    print(f"Wrote {REFERENCE_OUT}")

    report = {
        "stage": "K4c",
        "epsilon": EPSILON,
        "t1_grid": {
            "start": robust_gate.T1_START,
            "end": robust_gate.T1_END,
            "step": robust_gate.T1_STEP,
        },
        "t3_grid": "observed s3 values",
        "k_grid": list(robust_gate.K_GRID),
        "fit_deltas": list(robust_gate.FIT_DELTAS),
        "answerable": ans_count,
        "out_of_scope": oos_count,
        "oos_class_counts": oos_by_cls,
        "presets": report_presets,
        "selected": selected,
        "old_presets_on_same_signals": old_eval,
        "cv": cv_res,
    }
    os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(f"Wrote {REPORT_OUT}")

    # Print in full: rejected answerable and accepted OOS.
    for preset_name, params in (("balanced", bal_params), ("strict", str_params)):
        rej_ans = []
        acc_oos = []
        for r in rows:
            if accept(
                float(r["s1_top1"]),
                float(r["s3_cov_top3"]),
                float(r["s4_unknown"]),
                params,
            ):
                if not r["answerable"]:
                    acc_oos.append(r)
            elif r["answerable"]:
                rej_ans.append(r)

        print("\n==========================================")
        print(
            f"PRESET: {preset_name.upper()} "
            f"(t1={params['t1']:.9f}, t3={params['t3']:.9f}, k={params['k']})"
        )
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
