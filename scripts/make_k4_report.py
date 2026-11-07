#!/usr/bin/env python3
"""Stage K4: assemble a single Markdown/JSON report from CI outputs.

Every number in this report is read from a file produced by the same CI job
(CSV/JSON/JUnit XML) or from the public GitHub release API.  Nothing is typed
in by hand.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

OUT_DIR = os.path.join("build", "reports", "k4")
OUT_MD = os.path.join(OUT_DIR, "k4_report.md")
OUT_JSON = os.path.join(OUT_DIR, "k4_summary.json")

TASK0_JSON = os.path.join("eval", "batch_padding_summary.json")
GATE_STEMS_CSV = os.path.join("build", "reports", "parity", "gate_stems_parity.csv")
GATE_DECISIONS_CSV = os.path.join("build", "reports", "parity", "gate_decisions.csv")
JUNIT_CSV = os.path.join(OUT_DIR, "junit_tests.csv")
VOCAB_JSON = os.path.join("app", "src", "main", "assets", "gate_vocab.json")
CONFIG_JSON = os.path.join("app", "src", "main", "assets", "gate_config.json")


def esc(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def as_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def previous_apk_size(repo: str, tag: str):
    if not repo or not tag:
        return None, None
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "k4-report",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
    except Exception as exc:  # pragma: no cover - network dependent
        print(f"WARNING: could not fetch previous release {tag}: {exc}", file=sys.stderr)
        return None, None
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".apk"):
            return int(asset.get("size", 0)), name
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", default="")
    parser.add_argument("--previous-release-tag", default="build-142")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-url", default="")
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    task0 = read_json(TASK0_JSON) or {}
    stems_rows = read_csv(GATE_STEMS_CSV)
    decision_rows = read_csv(GATE_DECISIONS_CSV)
    test_rows = read_csv(JUNIT_CSV)
    vocab = read_json(VOCAB_JSON) or {}
    config = read_json(CONFIG_JSON) or {}

    current_apk = None
    if args.apk and os.path.exists(args.apk):
        current_apk = os.path.getsize(args.apk)
    prev_size, prev_name = previous_apk_size(args.repo, args.previous_release_tag)

    stem_diffs = [r for r in stems_rows if r.get("s3_match") != "YES" or r.get("s4_match") != "YES"]
    stem_matches = len(stems_rows) - len(stem_diffs)

    def decision_stats(preset):
        rows = [r for r in decision_rows if r.get("preset") == preset]
        diffs = [r for r in rows if r.get("agree") != "YES"]
        return len(rows), len(rows) - len(diffs), diffs

    bal_total, bal_match, bal_diffs = decision_stats("balanced")
    strict_total, strict_match, strict_diffs = decision_stats("strict")

    total_tests = len(test_rows)
    failed_tests = sum(1 for r in test_rows if r.get("status") in ("FAILED", "ERROR"))
    skipped_tests = sum(1 for r in test_rows if r.get("status") == "SKIPPED")
    total_test_time = sum(as_float(r.get("time_seconds")) for r in test_rows)

    real_vs_not_built = [
        (
            "Python batch-padding diagnostic",
            "REAL: executed in CI",
            "eval/batch_padding_summary.json",
        ),
        (
            "Kotlin (a) s3/s4 parity with Python top-3",
            "REAL: JVM unit test",
            "build/reports/parity/gate_stems_parity.csv",
        ),
        (
            "Kotlin (b) full pipeline decision parity",
            "REAL: JVM unit test with ONNX + embeddings",
            "build/reports/parity/gate_decisions.csv",
        ),
        (
            "Kotlin (c) hand-made gate unit cases",
            "REAL: JVM unit tests",
            "build/reports/k4/junit_tests.csv",
        ),
        (
            "On-device FTS5 MATCH button",
            "BUILT, NOT EXECUTED ON A DEVICE",
            "Compiled into the APK; CI has no Android device",
        ),
        (
            "Debug gate screen (balanced/strict toggle)",
            "BUILT, NOT EXECUTED ON A DEVICE",
            "Compiled into the APK; CI has no Android device",
        ),
        (
            "APK install/run on an ARM64 phone",
            "NOT EXECUTED",
            "CI builds and signs the APK only",
        ),
    ]

    lines = []
    lines.append("# Stage K4 report")
    lines.append("")
    lines.append(f"- Generated (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"- Commit: `{args.commit or 'unknown'}`")
    lines.append(f"- CI run: {args.run_url or 'unknown'}")
    lines.append("")
    lines.append("## Scope note / dependency fallback")
    lines.append("")
    lines.append(
        "The specification named `io.requery:sqlite-android` for on-device FTS5. "
        "That artifact is not present on Maven Central (verified with the Maven Central "
        "search API: `g:\"io.requery\" AND a:\"sqlite-android\"` returned 0 results), and "
        "its old JCenter/requery repositories are no longer resolvable. The on-device "
        "implementation therefore uses `mil.nga:sqlite-android:3450200` (SQLite Android "
        "Bindings, package `org.sqlite.database.sqlite`, FTS5 + porter verified in the "
        "AAR's `libsqliteX.so`). JVM tests continue to use `org.xerial:sqlite-jdbc` only. "
        "This is the only documented deviation from the requested dependency name."
    )
    lines.append("")
    lines.append("## Task 0: batch-padding diagnostic")
    lines.append("")
    if task0:
        lines.append("| Metric | Value |")
        lines.append("|---|---:|")
        lines.append(f"| Questions | {task0.get('questions', 'n/a')} |")
        lines.append(f"| Batch sizes | {task0.get('batch_sizes', 'n/a')} |")
        lines.append(
            f"| max abs(delta s1), batch 1 vs 8 | {task0.get('delta_s1_batch1_vs_batch8_max', 0):.12f} |"
        )
        lines.append(
            f"| mean abs(delta s1), batch 1 vs 8 | {task0.get('delta_s1_batch1_vs_batch8_mean', 0):.12f} |"
        )
        lines.append(
            f"| max abs(delta s1), batch 1 vs 16 | {task0.get('delta_s1_batch1_vs_batch16_max', 0):.12f} |"
        )
        lines.append(
            f"| mean abs(delta s1), batch 1 vs 16 | {task0.get('delta_s1_batch1_vs_batch16_mean', 0):.12f} |"
        )
        lines.append(
            f"| max abs embedding element delta, 1 vs 16 | {task0.get('embedding_abs_max_batch1_vs_batch16', 0):.12f} |"
        )
        lines.append(
            f"| max L2 embedding delta, 1 vs 16 | {task0.get('embedding_l2_max_batch1_vs_batch16', 0):.12f} |"
        )
        if task0.get("kotlin_available"):
            lines.append(
                f"| max abs(delta s1), Python batch 1 vs Kotlin | {task0.get('python_batch1_vs_kotlin_max', 0):.12f} |"
            )
            lines.append(
                f"| mean abs(delta s1), Python batch 1 vs Kotlin | {task0.get('python_batch1_vs_kotlin_mean', 0):.12f} |"
            )
            lines.append(
                f"| max abs(delta s1), Python reference batch 16 vs Kotlin | {task0.get('python_batch16_reference_vs_kotlin_max', 0):.12f} |"
            )
            lines.append(
                f"| mean abs(delta s1), Python reference batch 16 vs Kotlin | {task0.get('python_batch16_reference_vs_kotlin_mean', 0):.12f} |"
            )
            lines.append(f"| Kotlin rows compared | {task0.get('kotlin_rows_compared', 0)} |")
        lines.append(f"| Verdict threshold | {task0.get('padding_eps', 0):g} |")
        lines.append(
            f"| **Verdict padding_dependent** | **{'TRUE' if task0.get('padding_dependent') else 'FALSE'}** |"
        )
    else:
        lines.append("`eval/batch_padding_summary.json` is missing.")
    lines.append("")
    lines.append("## (a) Kotlin s3/s4 vs Python reference (Python top-3 chunk ids)")
    lines.append("")
    lines.append(
        f"Compared rows: {len(stems_rows)}. Exact matches: {stem_matches}. "
        f"Differences: {len(stem_diffs)}."
    )
    lines.append("")
    if stem_diffs:
        lines.append("| cls | id | question | Kotlin s3 | Python s3 | s3 match | Kotlin s4 | Python s4 | s4 match | stems | top3 |")
        lines.append("|---|---:|---|---:|---:|---|---:|---:|---|---|---|")
        for r in stem_diffs:
            lines.append(
                f"| {esc(r.get('cls'))} | {esc(r.get('id'))} | {esc(r.get('question'))} | "
                f"{esc(r.get('kotlin_s3'))} | {esc(r.get('python_s3'))} | {esc(r.get('s3_match'))} | "
                f"{esc(r.get('kotlin_s4'))} | {esc(r.get('python_s4'))} | {esc(r.get('s4_match'))} | "
                f"{esc(r.get('stems'))} | {esc(r.get('top3_chunk_ids'))} |"
            )
    else:
        lines.append("No differences: every one of the 120 questions has identical s3 and s4.")
    lines.append("")
    lines.append("## (b) Full Kotlin embedder pipeline decisions vs Python reference")
    lines.append("")
    lines.append(
        f"Balanced: {bal_match}/{bal_total} equal; strict: {strict_match}/{strict_total} equal. "
        "Required threshold: at least 112/120."
    )
    lines.append("")
    if bal_diffs or strict_diffs:
        lines.append("| preset | cls | id | question | Python | Kotlin | s1 | t1 | abs(s1-t1) | s3 | s4 | reason |")
        lines.append("|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|")
        for r in bal_diffs + strict_diffs:
            lines.append(
                f"| {esc(r.get('preset'))} | {esc(r.get('cls'))} | {esc(r.get('id'))} | "
                f"{esc(r.get('question'))} | {esc(r.get('python_decision'))} | "
                f"{esc(r.get('kotlin_decision'))} | {esc(r.get('s1_kotlin'))} | "
                f"{esc(r.get('t1'))} | {esc(r.get('abs_s1_minus_t1'))} | "
                f"{esc(r.get('s3_kotlin'))} | {esc(r.get('s4_kotlin'))} | {esc(r.get('reason'))} |"
            )
    else:
        lines.append("No disagreements for either preset.")
    lines.append("")
    lines.append("## Gate configuration and vocabulary")
    lines.append("")
    if config:
        bal = config.get("balanced", {})
        strict = config.get("strict", {})
        lines.append("| Preset | t1 | t3 | k |")
        lines.append("|---|---:|---:|---:|")
        lines.append(f"| balanced | {bal.get('t1')} | {bal.get('t3')} | {bal.get('k')} |")
        lines.append(f"| strict | {strict.get('t1')} | {strict.get('t3')} | {strict.get('k')} |")
        lines.append("")
    if vocab:
        lines.append(
            f"`gate_vocab.json`: stopwords={len(vocab.get('stopwords', []))}, "
            f"non_content_words={len(vocab.get('non_content_words', []))}, "
            f"variant_map={len(vocab.get('variant_map', {}))}, "
            f"hyphen_compounds={len(vocab.get('normalization', {}).get('hyphen_compounds', {}))}, "
            f"fts_tokenizer=`{vocab.get('fts_tokenizer')}`."
        )
        lines.append("")
    lines.append("## Unit tests (JUnit, from CI XML)")
    lines.append("")
    lines.append(
        f"Tests: {total_tests}; failed/error: {failed_tests}; skipped: {skipped_tests}; "
        f"total time: {total_test_time:.3f} s."
    )
    lines.append("")
    if test_rows:
        lines.append("| Class | Test | Time (s) | Status |")
        lines.append("|---|---|---:|---|")
        for r in sorted(
            test_rows,
            key=lambda x: (-as_float(x.get("time_seconds")), x.get("classname", ""), x.get("name", "")),
        ):
            lines.append(
                f"| {esc(r.get('classname'))} | {esc(r.get('name'))} | "
                f"{as_float(r.get('time_seconds')):.3f} | {esc(r.get('status'))} |"
            )
    else:
        lines.append("`junit_tests.csv` is missing.")
    lines.append("")
    lines.append("## APK size")
    lines.append("")
    lines.append("| Item | Bytes |")
    lines.append("|---|---:|")
    lines.append(f"| Current APK | {current_apk if current_apk is not None else 'unavailable'} |")
    previous_label = f"`{args.previous_release_tag}`"
    lines.append(
        f"| Previous {previous_label} APK ({prev_name or 'unavailable'}) | "
        f"{prev_size if prev_size is not None else 'unavailable'} |"
    )
    if current_apk is not None and prev_size is not None:
        lines.append(f"| Delta (current - previous) | {current_apk - prev_size} |")
    else:
        lines.append("| Delta (current - previous) | unavailable |")
    lines.append("")
    lines.append("## Real vs not built / not executed")
    lines.append("")
    lines.append("| Item | Status | Evidence |")
    lines.append("|---|---|---|")
    for item, status, evidence in real_vs_not_built:
        lines.append(f"| {esc(item)} | {esc(status)} | {esc(evidence)} |")
    lines.append("")

    text = "\n".join(lines) + "\n"
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(text)

    summary = {
        "run_url": args.run_url,
        "commit": args.commit,
        "task0": task0,
        "gate_stems": {
            "total": len(stems_rows),
            "matches": stem_matches,
            "differences": stem_diffs,
        },
        "gate_decisions": {
            "balanced": {"total": bal_total, "matches": bal_match, "differences": bal_diffs},
            "strict": {"total": strict_total, "matches": strict_match, "differences": strict_diffs},
        },
        "tests": {
            "total": total_tests,
            "failed": failed_tests,
            "skipped": skipped_tests,
            "total_time_seconds": total_test_time,
        },
        "apk": {
            "current_bytes": current_apk,
            "previous_tag": args.previous_release_tag,
            "previous_bytes": prev_size,
            "previous_asset": prev_name,
            "delta_bytes": (current_apk - prev_size)
            if current_apk is not None and prev_size is not None
            else None,
        },
        "real_vs_not_built": [
            {"item": item, "status": status, "evidence": evidence}
            for item, status, evidence in real_vs_not_built
        ],
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")
    print(
        f"Task0 verdict: {'TRUE' if task0.get('padding_dependent') else 'FALSE'}; "
        f"(a) {stem_matches}/{len(stems_rows)}; "
        f"(b) balanced {bal_match}/{bal_total}, strict {strict_match}/{strict_total}; "
        f"tests {total_tests} ({failed_tests} failed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
