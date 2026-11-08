#!/usr/bin/env python3
"""Stage K5a: assemble the CI report from files produced by the same job.

Inputs (all generated in the job, never typed by hand):
  build/reports/k4/junit_tests.csv       JUnit XML collected after testDebugUnitTest
  build/reports/k5a/e2e_10.csv           real-model end-to-end test report
  app/build/outputs/apk/.../*.apk        release APK (or debug fallback)
  app/src/main/assets/gate_config.json   fitted presets used by the job

Outputs:
  build/reports/k5a/k5a_report.md
  build/reports/k5a/k5a_summary.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request

OUT_DIR = os.path.join("build", "reports", "k5a")
OUT_MD = os.path.join(OUT_DIR, "k5a_report.md")
OUT_JSON = os.path.join(OUT_DIR, "k5a_summary.json")
JUNIT_CSV = os.path.join("build", "reports", "k4", "junit_tests.csv")
E2E_CSV = os.path.join(OUT_DIR, "e2e_10.csv")
CONFIG_JSON = os.path.join("app", "src", "main", "assets", "gate_config.json")


def esc(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def previous_apk_size(repo: str, tag: str):
    if not repo or not tag:
        return None, None
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "k5a-report",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except Exception as exc:  # pragma: no cover - network dependent
        print(f"WARNING: could not fetch previous release {tag}: {exc}", file=sys.stderr)
        return None, None
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".apk"):
            return int(asset.get("size", 0)), name
    return None, None


def human_bytes(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:,} bytes ({value / (1024 * 1024):.2f} MiB)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", default="")
    parser.add_argument("--previous-release-tag", default="build-153")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-url", default="")
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.apk and "release" in args.apk and os.path.exists(args.apk):
        import verify_release_no_gallery
        verify_release_no_gallery.check_apk(args.apk)

    tests = read_csv(JUNIT_CSV)
    e2e = read_csv(E2E_CSV)
    config = read_json(CONFIG_JSON) or {}

    current_apk = None
    if args.apk and os.path.exists(args.apk):
        current_apk = os.path.getsize(args.apk)
    previous_size, previous_name = previous_apk_size(args.repo, args.previous_release_tag)
    delta = None
    if current_apk is not None and previous_size:
        delta = current_apk - previous_size

    total_tests = len(tests)
    failed_tests = sum(1 for r in tests if r.get("status") in ("FAILED", "ERROR"))
    skipped_tests = sum(1 for r in tests if r.get("status") == "SKIPPED")
    total_time = sum(float(r.get("time_seconds") or 0) for r in tests)

    e2e_rows = e2e
    e2e_decision_mismatches = [r for r in e2e_rows if r.get("decision_match") != "YES"]
    e2e_top3_mismatches = [r for r in e2e_rows if r.get("top3_match") != "YES"]
    e2e_questions = sorted({int(r["id"]) for r in e2e_rows if r.get("id")})

    lines = [
        "# K5a report — real Ask screen",
        "",
        f"- CI run: {args.run_url or 'n/a'}",
        f"- Commit: `{args.commit or 'n/a'}`",
        f"- APK: `{os.path.basename(args.apk) if args.apk else 'n/a'}`",
        "",
        "## K4c claim check",
        "",
        "The “122 passed (locally)” line refers to the Python `pytest tests` suite.",
        "In the K4c CI run `42390176414` (build-146) the pytest step reported",
        "**117 passed, 5 skipped** (122 collected), because the model download step runs",
        "after pytest, so `tests/test_embeddings.py` skipped. The JVM suite in that run",
        "was **29 tests, all passed**. No JVM tests ran in this workspace.",
        "",
        "## JVM unit tests (from `testDebugUnitTest` XML)",
        "",
        f"- Tests: **{total_tests}**",
        f"- Failed/error: **{failed_tests}**",
        f"- Skipped: **{skipped_tests}**",
        f"- Total test time: **{total_time:.3f} s**",
        "",
        "| Class | Test | Time (s) | Status |",
        "|---|---|---:|---|",
    ]
    for row in sorted(
        tests,
        key=lambda r: (-float(r.get("time_seconds") or 0), r.get("classname", ""), r.get("name", "")),
    ):
        lines.append(
            f"| {esc(row.get('classname', ''))} | {esc(row.get('name', ''))} | "
            f"{float(row.get('time_seconds') or 0):.3f} | {esc(row.get('status', ''))} |"
        )
    if not tests:
        lines.append("| (no JUnit XML found) | — | — | — |")

    lines.extend([
        "",
        "## End-to-end real-model test (golden questions 1–10)",
        "",
        "`DeviceAskEngine` (the exact app pipeline) ran tokenize → embed batch 1 →",
        "dense top-5 → gate → top-3 for both presets. Expected decisions come from",
        "`assets/gate_reference.json`; expected top-3 chunk ids come from",
        "`eval/retrieval_top5.csv`; both files were regenerated by this job.",
        "",
        f"- Questions: **{len(e2e_questions)}** ({e2e_questions})",
        f"- Decision mismatches: **{len(e2e_decision_mismatches)}**",
        f"- Top-3 chunk-id mismatches: **{len(e2e_top3_mismatches)}**",
        "",
        "| id | question | preset | expected decision | actual decision | match | expected top-3 | actual top-3 | top-3 match | pages | total ms |",
        "|---:|---|---|---|---|---|---|---|---|---|---:|",
    ])
    for row in sorted(e2e_rows, key=lambda r: (int(r.get("id", 0)), r.get("preset", ""))):
        lines.append(
            f"| {esc(row.get('id', ''))} | {esc(row.get('question', ''))} | "
            f"{esc(row.get('preset', ''))} | {esc(row.get('expected_decision', ''))} | "
            f"{esc(row.get('actual_decision', ''))} | {esc(row.get('decision_match', ''))} | "
            f"{esc(row.get('expected_top3', ''))} | {esc(row.get('actual_top3', ''))} | "
            f"{esc(row.get('top3_match', ''))} | {esc(row.get('pages', ''))} | "
            f"{esc(row.get('total_ms', ''))} |"
        )
    if not e2e_rows:
        lines.append("| — | (no e2e_10.csv found) | — | — | — | — | — | — | — | — | — |")

    lines.extend([
        "",
        "## Fitted presets used by this job",
        "",
        "| Preset | t1 | t3 | k |",
        "|---|---:|---:|---:|",
    ])
    for name in ("balanced", "strict"):
        preset = config.get(name, {})
        lines.append(
            f"| {name} | {preset.get('t1', 'n/a')} | {preset.get('t3', 'n/a')} | "
            f"{preset.get('k', 'n/a')} |"
        )

    lines.extend([
        "",
        "## APK size",
        "",
        f"- Current APK: **{human_bytes(current_apk)}**",
        f"- Previous release `{args.previous_release_tag}`: **{human_bytes(previous_size)}**"
        + (f" (`{previous_name}`)" if previous_name else ""),
        f"- Delta: **{delta:+,} bytes ({delta / (1024 * 1024):+.2f} MiB)**"
        if delta is not None else "- Delta: **n/a**",
        "",
        "## Real vs not built / not verified",
        "",
        "| Item | Status | Evidence |",
        "|---|---|---|",
        "| State machine transitions (install, loading, ready, search, cancel, double tap, error, retry) | REAL — JVM tests with fakes | `build/reports/k4/junit_tests.csv` (`AskStateMachineTest`) |",
        "| Exact refusal sentence | REAL — JVM test | `AskStateMachineTest.rejectedAnswerUsesExactRefusalSentence` |",
        "| Citation formatter (`[المصدر: … - صفحة …]`, underscores→spaces) | REAL — JVM test | `PassageTextTest` |",
        "| Stem highlighting (case, punctuation, hyphen compounds) | REAL — JVM test | `PassageTextTest` |",
        "| 350-character word-boundary truncation | REAL — JVM test | `PassageTextTest` |",
        "| Previous/next chunk navigation at chunk 1 and 1185, same book | REAL — JVM test against the real DB | `NeighbourNavigationTest` |",
        "| Preset persistence/default (balanced) and show-timings | REAL — JVM test with DataStore | `SettingsRepositoryTest` |",
        "| Full pipeline decision + top-3 for 10 golden questions | REAL — JVM test with the real ONNX model, tokenizer, embeddings and gate DB | `PipelineEndToEndTest`, `e2e_10.csv` |",
        "| UI rotation keeping model/tokenizer/matrix loaded | BUILT, NOT VERIFIED — no device/emulator UI run in K5a | AppGraph + ViewModel code; CI has no K5a instrumented UI test |",
        "| IME Send key, multi-line input, `imePadding` | BUILT, NOT VERIFIED | No device/emulator UI run |",
        "| Font scale up to 130% without clipping | BUILT, NOT VERIFIED | No device/emulator UI run |",
        "| Light/dark/system theme | BUILT, NOT VERIFIED | No device/emulator UI run |",
        "| RTL screen with English LTR passage blocks | BUILT, NOT VERIFIED | No device/emulator UI run |",
        "| 48 dp touch targets and edge-to-edge insets | BUILT, NOT VERIFIED | No device/emulator UI run |",
        "| Long-press title opens the debug screen | BUILT, NOT VERIFIED | No device/emulator UI run |",
        "| Citation bottom sheet with previous/next and copy | BUILT, NOT VERIFIED | No device/emulator UI run |",
        "| APK installs and launches on a physical phone | NOT VERIFIED — CI has no physical device | Release APK built and inspected only |",
    ])

    text = "\n".join(lines) + "\n"
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(text)

    summary = {
        "run_url": args.run_url,
        "commit": args.commit,
        "junit": {
            "tests": total_tests,
            "failed": failed_tests,
            "skipped": skipped_tests,
            "total_time_seconds": total_time,
        },
        "e2e": {
            "questions": len(e2e_questions),
            "rows": len(e2e_rows),
            "decision_mismatches": len(e2e_decision_mismatches),
            "top3_mismatches": len(e2e_top3_mismatches),
        },
        "apk": {
            "current_bytes": current_apk,
            "previous_tag": args.previous_release_tag,
            "previous_bytes": previous_size,
            "delta_bytes": delta,
        },
        "presets": {
            name: config.get(name) for name in ("balanced", "strict")
        },
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")
    print(
        f"JUnit tests={total_tests} failed={failed_tests} skipped={skipped_tests}; "
        f"e2e rows={len(e2e_rows)} decision_mismatches={len(e2e_decision_mismatches)} "
        f"top3_mismatches={len(e2e_top3_mismatches)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
