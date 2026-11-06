#!/usr/bin/env python3
"""Summarize the Kotlin-vs-Python retrieval parity report (K3c).

Reads build/reports/parity/retrieval_parity.csv and reports:
  - number of rows
  - top-1 identical count and percentage
  - max / p95 / mean of |delta s1|

p95 uses numpy.percentile's default linear interpolation; the method is printed
so the number can be reproduced. Writes a small CSV summary next to the input
and, when GITHUB_STEP_SUMMARY is set, a Markdown table to the step summary.
"""
from __future__ import annotations

import csv
import os
import sys

import numpy as np

DEFAULT_REPORT = os.path.join("build", "reports", "parity", "retrieval_parity.csv")
P95_METHOD = "linear interpolation (numpy.percentile default)"


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPORT
    if not os.path.exists(path):
        print(f"ERROR: parity report not found: {path}", file=sys.stderr)
        return 1

    with open(path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"ERROR: parity report has no data rows: {path}", file=sys.stderr)
        return 1

    required = {"python_top1_chunk", "kotlin_top1_chunk", "python_s1", "kotlin_s1"}
    missing = required - set(rows[0].keys())
    if missing:
        print(f"ERROR: parity report is missing columns: {sorted(missing)}", file=sys.stderr)
        return 1

    total = len(rows)
    top1_identical = sum(
        1
        for r in rows
        if r["python_top1_chunk"].strip() == r["kotlin_top1_chunk"].strip()
    )

    deltas = np.abs(
        np.asarray(
            [float(r["python_s1"]) - float(r["kotlin_s1"]) for r in rows],
            dtype=np.float64,
        )
    )
    delta_max = float(np.max(deltas))
    delta_p95 = float(np.percentile(deltas, 95))
    delta_mean = float(np.mean(deltas))
    top1_pct = 100.0 * top1_identical / total

    summary_lines = [
        "metric,value",
        f"rows,{total}",
        f"top1_identical,{top1_identical}",
        f"top1_identical_pct,{top1_pct:.6f}",
        f"delta_s1_max,{delta_max:.9f}",
        f"delta_s1_p95,{delta_p95:.9f}",
        f"delta_s1_mean,{delta_mean:.9f}",
        f"p95_method,\"{P95_METHOD}\"",
    ]
    out_path = os.path.splitext(path)[0] + "_summary.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(summary_lines) + "\n")

    print(f"Report: {path}")
    print(f"Rows: {total}")
    print(f"Top-1 identical: {top1_identical}/{total} ({top1_pct:.2f}%)")
    print(f"|delta s1| max: {delta_max:.9f}")
    print(f"|delta s1| p95: {delta_p95:.9f}  [{P95_METHOD}]")
    print(f"|delta s1| mean: {delta_mean:.9f}")
    print(f"Wrote {out_path}")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n### K3c retrieval parity (Kotlin vs Python)\n\n")
            f.write("| Metric | Value |\n|---|---|\n")
            f.write(f"| Rows | {total} |\n")
            f.write(f"| Top-1 identical | {top1_identical}/{total} ({top1_pct:.2f}%) |\n")
            f.write(f"| abs(delta s1) max | {delta_max:.9f} |\n")
            f.write(f"| abs(delta s1) p95 | {delta_p95:.9f} |\n")
            f.write(f"| abs(delta s1) mean | {delta_mean:.9f} |\n")
            f.write(f"| p95 method | {P95_METHOD} |\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
