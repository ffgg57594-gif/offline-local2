#!/usr/bin/env python3
"""K4b: compare two gate_signals.csv files measured on different CI CPUs.

Criterion 6 asks, when a workflow_dispatch rerun lands on another CPU type:
  * embeddings.bin sha256 and CPU model for both runs;
  * max / mean |delta s1| over the 120 questions;
  * number of questions whose top-1 chunk changed.

Usage:
  python scripts/k4b_compare_cpu.py \
      --a run1/gate_signals.csv --meta-a run1/retrieval_top5.meta.json \
      --b run2/gate_signals.csv --meta-b run2/retrieval_top5.meta.json

Output: build/reports/k4b/cpu_comparison.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

OUT_JSON = os.path.join("build", "reports", "k4b", "cpu_comparison.json")


def read_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    by_key = {}
    for r in rows:
        by_key[(r["group"], int(r["id"]))] = r
    return by_key


def read_meta(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--meta-a", default="")
    parser.add_argument("--meta-b", default="")
    args = parser.parse_args()

    a = read_csv(args.a)
    b = read_csv(args.b)
    if set(a) != set(b):
        print("ERROR: the two CSVs do not contain the same (group, id) keys", file=sys.stderr)
        return 1

    deltas = []
    changed_top1 = []
    for key in sorted(a):
        s1a = float(a[key]["s1_top1"])
        s1b = float(b[key]["s1_top1"])
        deltas.append(abs(s1a - s1b))
        if a[key]["top1_chunk_id"] != b[key]["top1_chunk_id"]:
            changed_top1.append({
                "group": key[0],
                "id": key[1],
                "top1_a": int(a[key]["top1_chunk_id"]),
                "top1_b": int(b[key]["top1_chunk_id"]),
                "s1_a": s1a,
                "s1_b": s1b,
                "abs_delta_s1": abs(s1a - s1b),
            })

    meta_a = read_meta(args.meta_a)
    meta_b = read_meta(args.meta_b)
    result = {
        "a": {
            "gate_signals_csv": args.a,
            "embeddings_bin_sha256": meta_a.get("embeddings_bin_sha256"),
            "cpu_model": meta_a.get("cpu_model"),
            "retrieval_top5_csv_sha256": meta_a.get("retrieval_top5_csv_sha256"),
        },
        "b": {
            "gate_signals_csv": args.b,
            "embeddings_bin_sha256": meta_b.get("embeddings_bin_sha256"),
            "cpu_model": meta_b.get("cpu_model"),
            "retrieval_top5_csv_sha256": meta_b.get("retrieval_top5_csv_sha256"),
        },
        "questions": len(deltas),
        "delta_s1_max": max(deltas),
        "delta_s1_mean": sum(deltas) / len(deltas),
        "changed_top1_count": len(changed_top1),
        "changed_top1": changed_top1,
        "same_cpu": meta_a.get("cpu_model") == meta_b.get("cpu_model"),
        "same_embeddings_sha256": (
            meta_a.get("embeddings_bin_sha256") == meta_b.get("embeddings_bin_sha256")
        ),
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    print("| Run | CPU model | embeddings.bin sha256 |")
    print("|---|---|---|")
    print(f"| A | {result['a']['cpu_model']} | `{result['a']['embeddings_bin_sha256']}` |")
    print(f"| B | {result['b']['cpu_model']} | `{result['b']['embeddings_bin_sha256']}` |")
    print("")
    print(f"Questions compared: {result['questions']}")
    print(f"max |delta s1|: {result['delta_s1_max']:.12f}")
    print(f"mean |delta s1|: {result['delta_s1_mean']:.12f}")
    print(f"changed top-1 chunks: {result['changed_top1_count']}/{result['questions']}")
    if changed_top1:
        print("\n| group | id | top1 A | top1 B | s1 A | s1 B | abs(delta s1) |")
        print("|---|---:|---:|---:|---:|---:|---:|")
        for c in changed_top1:
            print(
                f"| {c['group']} | {c['id']} | {c['top1_a']} | {c['top1_b']} | "
                f"{c['s1_a']:.9f} | {c['s1_b']:.9f} | {c['abs_delta_s1']:.9f} |"
            )
    print(f"\nWrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
