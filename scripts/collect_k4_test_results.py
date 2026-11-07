#!/usr/bin/env python3
"""Stage K4: collect Gradle unit-test results (name, duration, status)."""
from __future__ import annotations

import csv
import glob
import os
import sys
import xml.etree.ElementTree as ET

RESULT_GLOBS = [
    os.path.join("app", "build", "test-results", "testDebugUnitTest", "*.xml"),
    os.path.join("build", "test-results", "testDebugUnitTest", "*.xml"),
]
OUT_DIR = os.path.join("build", "reports", "k4")
OUT_CSV = os.path.join(OUT_DIR, "junit_tests.csv")
OUT_MD = os.path.join(OUT_DIR, "junit_summary.md")


def status_of(case: ET.Element) -> str:
    if case.find("failure") is not None:
        return "FAILED"
    if case.find("error") is not None:
        return "ERROR"
    if case.find("skipped") is not None:
        return "SKIPPED"
    return "PASSED"


def collect():
    files = []
    for pattern in RESULT_GLOBS:
        files.extend(glob.glob(pattern))
    files = sorted(set(files))
    rows = []
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            print(f"WARNING: cannot parse {path}: {exc}", file=sys.stderr)
            continue
        for case in root.iter("testcase"):
            rows.append(
                {
                    "classname": case.attrib.get("classname", ""),
                    "name": case.attrib.get("name", ""),
                    "time_seconds": case.attrib.get("time", "0"),
                    "status": status_of(case),
                    "file": os.path.basename(path),
                }
            )
    rows.sort(key=lambda r: (r["classname"], r["name"]))
    return files, rows


def main() -> int:
    files, rows = collect()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["classname", "name", "time_seconds", "status", "file"]
        )
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    failed = sum(1 for r in rows if r["status"] in ("FAILED", "ERROR"))
    skipped = sum(1 for r in rows if r["status"] == "SKIPPED")
    total_time = sum(float(r["time_seconds"] or 0) for r in rows)

    lines = [
        "# JUnit test summary",
        "",
        f"- XML files: {len(files)}",
        f"- Tests: {total}",
        f"- Failed/error: {failed}",
        f"- Skipped: {skipped}",
        f"- Total time: {total_time:.3f} s",
        "",
        "| Class | Test | Time (s) | Status |",
        "|---|---|---:|---|",
    ]
    for r in sorted(rows, key=lambda x: (-float(x["time_seconds"] or 0), x["classname"], x["name"])):
        lines.append(
            f"| {r['classname']} | {r['name']} | {float(r['time_seconds'] or 0):.3f} | {r['status']} |"
        )
    text = "\n".join(lines) + "\n"
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Wrote {OUT_CSV} ({total} tests from {len(files)} XML files)")
    print(f"Wrote {OUT_MD}")
    print(f"Tests: {total}, failed/error: {failed}, skipped: {skipped}, time: {total_time:.3f}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
