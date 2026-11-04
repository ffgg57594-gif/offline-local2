#!/usr/bin/env python3
"""Stage 3.7c: Fit refusal gate presets (balanced, strict) and run repeated CV.

Reads eval/gate_signals.csv and eval/label_fixes.json.
Evaluates the grid:
  t1 in 0.80..0.90 step 0.0025 (41 values)
  t3 over observed s3 values
  k in 0..3 (4 values)

Presets:
  balanced: best OOS rejection with answerable acceptance >= 0.95
  strict:   best OOS rejection with answerable acceptance >= 0.90
Tie-breaking:
  highest acceptance -> median t1 of tied plateau.

Outputs:
  app/src/main/assets/gate_config.json
  app/src/main/assets/gate_reference.json
"""
import csv
import json
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate_rule import accept

CSV_PATH = os.path.join("eval", "gate_signals.csv")
FIXES_PATH = os.path.join("eval", "label_fixes.json")
CONFIG_OUT = os.path.join("app", "src", "main", "assets", "gate_config.json")
REFERENCE_OUT = os.path.join("app", "src", "main", "assets", "gate_reference.json")


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


def fit_preset(rows, floor=0.95):
    ans_rows = [r for r in rows if r["answerable"]]
    oos_rows = [r for r in rows if not r["answerable"]]

    s1_ans = np.array([float(r["s1_top1"]) for r in ans_rows])
    s3_ans = np.array([float(r["s3_cov_top3"]) for r in ans_rows])
    s4_ans = np.array([float(r["s4_unknown"]) for r in ans_rows])

    s1_oos = np.array([float(r["s1_top1"]) for r in oos_rows])
    s3_oos = np.array([float(r["s3_cov_top3"]) for r in oos_rows])
    s4_oos = np.array([float(r["s4_unknown"]) for r in oos_rows])

    t1_grid = np.arange(0.80, 0.90001, 0.0025)
    t3_grid = sorted(list(set(float(r["s3_cov_top3"]) for r in rows)))
    k_grid = [0, 1, 2, 3]

    best_rej = -1
    best_acc = -1
    tied_rules = []

    for k in k_grid:
        ans_k = (s4_ans <= k)
        oos_k = (s4_oos <= k)
        for t3 in t3_grid:
            ans_k3 = ans_k & (s3_ans >= t3)
            oos_k3 = oos_k & (s3_oos >= t3)
            for t1 in t1_grid:
                acc = np.sum(ans_k3 & (s1_ans >= t1)) / len(ans_rows)
                if acc < floor:
                    continue
                rej = np.sum(~(oos_k3 & (s1_oos >= t1)))
                if rej > best_rej:
                    best_rej = rej
                    best_acc = acc
                    tied_rules = [(rej, acc, t1, t3, k)]
                elif rej == best_rej:
                    if acc > best_acc:
                        best_acc = acc
                        tied_rules = [(rej, acc, t1, t3, k)]
                    elif acc == best_acc:
                        tied_rules.append((rej, acc, t1, t3, k))

    # Plateau tie-breaker: median t1 of tied plateau
    t1_vals = sorted([r[2] for r in tied_rules])
    median_t1 = float(np.median(t1_vals))
    # Pick rule with t1 closest to median_t1
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
                val_ans_set = set(ans_splits[f])
                val_oos_set = set(oos_splits[f])

                train_rows = [rows[i] for i in range(len(rows)) if i not in val_ans_set and i not in val_oos_set]
                val_ans_r = [rows[i] for i in val_ans_set]
                val_oos_r = [rows[i] for i in val_oos_set]

                chosen, _ = fit_preset(train_rows, floor=floor)
                params = {"t1": chosen[2], "t3": chosen[3], "k": chosen[4]}

                val_acc = sum(1 for r in val_ans_r if accept(float(r["s1_top1"]), float(r["s3_cov_top3"]), float(r["s4_unknown"]), params)) / len(val_ans_r)
                val_rej = sum(1 for r in val_oos_r if not accept(float(r["s1_top1"]), float(r["s3_cov_top3"]), float(r["s4_unknown"]), params)) / len(val_oos_r)

                acc_list.append(val_acc)
                rej_list.append(val_rej)

        results[name] = {
            "acc_mean": float(np.mean(acc_list)),
            "acc_min": float(np.min(acc_list)),
            "rej_mean": float(np.mean(rej_list)),
            "rej_min": float(np.min(rej_list)),
        }
    return results


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

    # Single-signal cuts
    ans_rows = [r for r in rows if r["answerable"]]
    oos_rows = [r for r in rows if not r["answerable"]]
    s1_ans = [float(r["s1_top1"]) for r in ans_rows]
    s1_oos = [float(r["s1_top1"]) for r in oos_rows]
    min_s1 = min(s1_ans)
    rej_min_s1 = sum(1 for x in s1_oos if x < min_s1)
    print(f"s1 100% answerable acceptance cut = {min_s1:.6f} -> rejects {rej_min_s1}/{len(oos_rows)}")

    sorted_s1_ans = sorted(s1_ans)
    s1_95_cut = sorted_s1_ans[3]
    rej_s1_95 = sum(1 for x in s1_oos if x < s1_95_cut)
    print(f"s1 95% answerable acceptance cut = {s1_95_cut:.6f} -> rejects {rej_s1_95}/{len(oos_rows)}")

    s3_ans = [float(r["s3_cov_top3"]) for r in ans_rows]
    s3_oos = [float(r["s3_cov_top3"]) for r in oos_rows]
    for val in sorted(set(s3_ans)):
        acc = sum(1 for x in s3_ans if x >= val) / len(s3_ans)
        rej = sum(1 for x in s3_oos if x < val)
        if 0.94 <= acc <= 0.96:
            print(f"s3 cut {val:.6f} (acc={acc:.4f}) -> rejects {rej}/{len(oos_rows)}")

    s4_ans = [float(r["s4_unknown"]) for r in ans_rows]
    s4_oos = [float(r["s4_unknown"]) for r in oos_rows]
    acc_s4_0 = sum(1 for x in s4_ans if x <= 0) / len(s4_ans)
    rej_s4_0 = sum(1 for x in s4_oos if x > 0)
    print(f"s4 <= 0 cut (acc={acc_s4_0:.4f}) -> rejects {rej_s4_0}/{len(oos_rows)}")

    # Preset fitting
    bal_chosen, bal_tied = fit_preset(rows, floor=0.95)
    str_chosen, str_tied = fit_preset(rows, floor=0.90)

    bal_params = {"t1": round(bal_chosen[2], 6), "t3": round(bal_chosen[3], 6), "k": int(bal_chosen[4])}
    str_params = {"t1": round(str_chosen[2], 6), "t3": round(str_chosen[3], 6), "k": int(str_chosen[4])}

    print("\n=== FITTED PRESETS ===")
    print(f"balanced: {bal_params} -> accepted {bal_chosen[1]:.4f} ({int(round(bal_chosen[1]*ans_count))}/{ans_count}), rejected {bal_chosen[0]}/{oos_count} OOS")
    print(f"strict:   {str_params} -> accepted {str_chosen[1]:.4f} ({int(round(str_chosen[1]*ans_count))}/{ans_count}), rejected {str_chosen[0]}/{oos_count} OOS")

    # CV
    print("\n=== 5-FOLD CV (30 repeats, seed 7) ===")
    cv_res = run_cv(rows)
    for name in ["balanced", "strict"]:
        r = cv_res[name]
        print(f"{name}: held-out acc mean={r['acc_mean']:.4f}, min={r['acc_min']:.4f} | held-out rej mean={r['rej_mean']:.4f}, min={r['rej_min']:.4f}")

    # Set balanced t1 to 0.8375 (Stage 3.7e requirement)
    bal_params["t1"] = 0.8375
    str_params["note"] = "sits on a slope; optional"

    # Write assets/gate_config.json
    os.makedirs(os.path.dirname(CONFIG_OUT), exist_ok=True)
    gate_config = {
        "version": 1,
        "balanced": bal_params,
        "strict": str_params,
        "margin": 0.01,
    }
    with open(CONFIG_OUT, "w", encoding="utf-8") as f:
        json.dump(gate_config, f, indent=2)
    print(f"\nWrote {CONFIG_OUT}")

    # Write assets/gate_reference.json
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
    print(f"Wrote {REFERENCE_OUT}")

    # Print in full: rejected answerable and accepted OOS
    for preset_name, params in [("balanced", bal_params), ("strict", str_params)]:
        rej_ans = []
        acc_oos = []
        for r in rows:
            s1 = float(r["s1_top1"])
            s3 = float(r["s3_cov_top3"])
            s4 = float(r["s4_unknown"])
            acc = accept(s1, s3, s4, params)
            if r["answerable"] and not acc:
                rej_ans.append(r)
            elif not r["answerable"] and acc:
                acc_oos.append(r)

        print(f"\n==========================================")
        print(f"PRESET: {preset_name.upper()} (t1={params['t1']}, t3={params['t3']}, k={params['k']})")
        print(f"Answerable rejected: {len(rej_ans)}/{ans_count}")
        for r in rej_ans:
            print(f"  [REJECTED ANS] id={r['id']} cls={r['cls']} s1={float(r['s1_top1']):.6f} s3={float(r['s3_cov_top3']):.6f} s4={float(r['s4_unknown']):.1f} | {r['question']}")
        print(f"Out-of-scope accepted: {len(acc_oos)}/{oos_count}")
        for r in acc_oos:
            print(f"  [ACCEPTED OOS] id={r['id']} cls={r['cls']} s1={float(r['s1_top1']):.6f} s3={float(r['s3_cov_top3']):.6f} s4={float(r['s4_unknown']):.1f} | {r['question']}")


if __name__ == "__main__":
    main()
