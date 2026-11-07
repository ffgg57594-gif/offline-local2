#!/usr/bin/env python3
"""Stage K4d: assemble the emulator/APK report from CI outputs.

All numbers are read from files produced by the same CI job (APKs, the
emulator log, the androidTest XML collector) or from the public GitHub release
API. Nothing is typed in by hand.

Outputs:
  build/reports/k4d/k4d_report.md
  build/reports/k4d/k4d_summary.json
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time
import urllib.request
import zipfile


def read_device_info(path: str) -> dict[str, str]:
    info: dict[str, str] = {}
    if not os.path.exists(path):
        return info
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    return info


def apk_info(pattern: str):
    matches = sorted(glob.glob(pattern))
    if not matches:
        return None
    path = matches[0]
    abis = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.startswith("lib/") and "/" in name[len("lib/"):]:
                    abis.add(name.split("/")[1])
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"WARNING: cannot inspect {path}: {exc}", file=sys.stderr)
    return {
        "path": path,
        "size_bytes": os.path.getsize(path),
        "abi_directories": sorted(abis),
    }


def previous_release(repo: str, current_tag: str):
    if not repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases?per_page=20"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "k4d-report"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            releases = json.load(response)
    except Exception as exc:  # pragma: no cover - network dependent
        print(f"WARNING: cannot fetch releases for {repo}: {exc}", file=sys.stderr)
        return None
    for release in releases:
        tag = release.get("tag_name", "")
        if tag == current_tag:
            continue
        for asset in release.get("assets", []):
            if asset.get("name", "").endswith(".apk"):
                return {
                    "tag": tag,
                    "asset": asset.get("name", ""),
                    "size_bytes": int(asset.get("size", 0)),
                }
    return None


def read_tests(path: str) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def fmt_bytes(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value} ({value / (1024 * 1024):.2f} MiB)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--current-tag", default="")
    parser.add_argument("--job-start-epoch", type=float, default=0.0)
    parser.add_argument("--out-dir", default=os.path.join("build", "reports", "k4d"))
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    device = read_device_info(os.path.join(args.out_dir, "device_info.txt"))
    debug_apk = apk_info(os.path.join("app", "build", "outputs", "apk", "debug", "*.apk"))
    release_apk = apk_info(
        os.path.join("app", "build", "outputs", "apk", "release", "*.apk")
    )
    previous = previous_release(args.repo, args.current_tag)
    tests = read_tests(os.path.join(args.out_dir, "android_test_results.csv"))

    now = time.time()
    total_job_seconds = (
        int(now - args.job_start_epoch) if args.job_start_epoch > 0 else None
    )

    size_delta = None
    size_delta_percent = None
    if release_apk and previous and previous.get("size_bytes"):
        size_delta = release_apk["size_bytes"] - previous["size_bytes"]
        size_delta_percent = 100.0 * size_delta / previous["size_bytes"]

    passed = sum(1 for row in tests if row.get("status") == "PASS")
    failed = sum(1 for row in tests if row.get("status") in ("FAIL", "ERROR"))
    skipped = sum(1 for row in tests if row.get("status") == "SKIP")

    lines: list[str] = []
    lines.append("# Stage K4d report")
    lines.append("")
    lines.append("## Emulator")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    for key in (
        "model",
        "device",
        "api",
        "release",
        "abi",
        "abilist",
        "emulator_boot_seconds",
        "connected_test_seconds",
    ):
        lines.append(f"| {key} | {device.get(key, 'n/a')} |")
    lines.append(
        f"| total_job_seconds | {total_job_seconds if total_job_seconds is not None else 'n/a'} |"
    )
    lines.append("")

    lines.append("## APK size, ABI and delta")
    lines.append("")
    lines.append("| APK | Path | Size | ABI directories |")
    lines.append("|---|---|---:|---|")
    for label, info in (("debug", debug_apk), ("release", release_apk)):
        if info is None:
            lines.append(f"| {label} | not built | n/a | n/a |")
        else:
            lines.append(
                f"| {label} | `{info['path']}` | {fmt_bytes(info['size_bytes'])} | "
                f"{', '.join(info['abi_directories']) or 'none'} |"
            )
    lines.append("")
    if previous and release_apk:
        lines.append(
            f"Previous release: `{previous['tag']}` / `{previous['asset']}` "
            f"= {fmt_bytes(previous['size_bytes'])}"
        )
        lines.append("")
        lines.append(
            f"Release APK delta: {size_delta:+d} bytes "
            f"({size_delta_percent:+.4f}%) versus `{previous['tag']}`."
        )
    else:
        lines.append("Previous-release delta: n/a (no comparable release/APK found).")
    lines.append("")

    lines.append("## Instrumented tests")
    lines.append("")
    lines.append(
        f"Tests: {len(tests)}; passed: {passed}; failed/error: {failed}; skipped: {skipped}."
    )
    lines.append("")
    lines.append("| Class | Test | Time (s) | Status |")
    lines.append("|---|---|---:|---|")
    for row in tests:
        lines.append(
            f"| {row.get('classname', '')} | {row.get('test', '')} | "
            f"{row.get('time_seconds', '')} | {row.get('status', '')} |"
        )
    lines.append("")

    report_text = "\n".join(lines) + "\n"
    report_path = os.path.join(args.out_dir, "k4d_report.md")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(report_text)

    summary = {
        "device": device,
        "total_job_seconds": total_job_seconds,
        "debug_apk": debug_apk,
        "release_apk": release_apk,
        "previous_release": previous,
        "release_size_delta_bytes": size_delta,
        "release_size_delta_percent": size_delta_percent,
        "android_tests": {
            "total": len(tests),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "rows": tests,
        },
    }
    summary_path = os.path.join(args.out_dir, "k4d_summary.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(report_text)
    print(f"Wrote {report_path} and {summary_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
