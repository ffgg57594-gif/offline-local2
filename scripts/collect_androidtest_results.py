#!/usr/bin/env python3
"""Collect connectedDebugAndroidTest XML results for the K4d report."""

from __future__ import annotations

import csv
import pathlib
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path("app/build/outputs/androidTest-results")
OUT_DIR = pathlib.Path("build/reports/k4d")


def find_xml() -> list[pathlib.Path]:
    if not ROOT.exists():
        return []
    return sorted(ROOT.rglob("*.xml"))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = find_xml()
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for xml_file in files:
        try:
            tree = ET.parse(xml_file)
        except ET.ParseError as exc:
            print(f"WARN: cannot parse {xml_file}: {exc}", file=sys.stderr)
            continue
        root = tree.getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for suite in suites:
            for case in suite.iter("testcase"):
                status = "PASS"
                failure = case.find("failure")
                error = case.find("error")
                skipped = case.find("skipped")
                if failure is not None:
                    status = "FAIL"
                elif error is not None:
                    status = "ERROR"
                elif skipped is not None:
                    status = "SKIP"
                key = (case.attrib.get("classname", ""), case.attrib.get("name", ""))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "classname": case.attrib.get("classname", ""),
                        "test": case.attrib.get("name", ""),
                        "time_seconds": case.attrib.get("time", ""),
                        "status": status,
                        "source_xml": str(xml_file),
                    }
                )

    rows.sort(key=lambda r: (r["classname"], r["test"]))
    csv_path = OUT_DIR / "android_test_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["classname", "test", "time_seconds", "status", "source_xml"],
        )
        writer.writeheader()
        writer.writerows(rows)

    passed = sum(1 for r in rows if r["status"] == "PASS")
    failed = sum(1 for r in rows if r["status"] in ("FAIL", "ERROR"))
    skipped = sum(1 for r in rows if r["status"] == "SKIP")

    md = OUT_DIR / "android_test_summary.md"
    lines = [
        "# K4d androidTest results",
        "",
        f"- XML files: {len(files)}",
        f"- Tests: {len(rows)}",
        f"- Passed: {passed}",
        f"- Failed/Error: {failed}",
        f"- Skipped: {skipped}",
        "",
        "| Class | Test | Time (s) | Status |",
        "|---|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['classname']} | {row['test']} | {row['time_seconds']} | {row['status']} |"
        )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print(f"\nWrote {csv_path} and {md}")
    if not rows:
        print("ERROR: no androidTest XML results found", file=sys.stderr)
        return 1
    if failed > 0:
        print(f"ERROR: {failed} androidTest case(s) failed/errored", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
