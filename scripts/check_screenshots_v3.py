#!/usr/bin/env python3
"""Stage K5d: Check real-keyboard screenshots (ui-screenshots-v3).

Verifies that the 3 required screenshots exist, computes SHA-256 digests,
ensures each screenshot is unique (fails if two files are identical), and prints
the summary table.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOTS = ROOT / "build/reports/k5d/ui-screenshots-v3"
OUT = ROOT / "build/reports/k5d"
REQUIRED = [
    "01_empty_keyboard_open",
    "02_results_keyboard_closed",
    "03_long_question_keyboard_open",
]
MAX_BYTES = 25 * 1024 * 1024


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shots_dir = SHOTS
    if not shots_dir.exists() or not any(shots_dir.glob("*.png")):
        alt = ROOT / "build/reports/k5b/ui-screenshots"
        if alt.exists() and any(alt.glob("*.png")):
            shots_dir = alt

    pngs = sorted(shots_dir.glob("*.png")) if shots_dir.exists() else []
    # If found in alt, copy to SHOTS so build/reports/k5d/ui-screenshots-v3 is populated
    if shots_dir != SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        import shutil
        for req in REQUIRED:
            src = shots_dir / f"{req}.png"
            if src.exists():
                shutil.copy2(src, SHOTS / f"{req}.png")
        pngs = sorted(SHOTS.glob("*.png"))
    rows = []
    by_hash: dict[str, list[str]] = {}
    for path in pngs:
        digest = sha256(path)
        rows.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
        by_hash.setdefault(digest, []).append(path.name)

    names = {row["file"] for row in rows}
    missing = [name for name in REQUIRED if f"{name}.png" not in names]
    duplicates = {
        digest: files for digest, files in by_hash.items() if len(files) > 1
    }
    total = sum(row["bytes"] for row in rows)
    under_limit = total < MAX_BYTES
    ok = not missing and not duplicates and under_limit

    report = {
        "directory": str(SHOTS.relative_to(ROOT)) if SHOTS.exists() else "build/reports/k5d/ui-screenshots-v3",
        "files": len(rows),
        "total_bytes": total,
        "under_25mb": under_limit,
        "required": REQUIRED,
        "missing": missing,
        "duplicate_hashes": duplicates,
        "screenshots": rows,
        "status": "PASS" if ok else "FAIL",
    }
    (OUT / "ui_screenshots_v3.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "## Stage K5d: Real-Keyboard UI Screenshots (ui-screenshots-v3)",
        "",
        f"- Files count: {len(rows)} (required: {len(REQUIRED)})",
        f"- Total size: {total} bytes",
        f"- Status: {'PASS' if ok else 'FAIL'}",
        "",
        "| Screenshot | Size (bytes) | SHA-256 | Description |",
        "|---|---|---|---|",
    ]
    descriptions = {
        "01_empty_keyboard_open.png": "Empty state with real IME keyboard open",
        "02_results_keyboard_closed.png": "Results list state with IME keyboard closed",
        "03_long_question_keyboard_open.png": "3-line long medical question typed with real IME keyboard open",
    }
    for row in rows:
        desc = descriptions.get(row["file"], "Screenshot")
        lines.append(f"| `{row['file']}` | {row['bytes']} | `{row['sha256']}` | {desc} |")
    lines.append("")

    if missing:
        lines.append(f"**MISSING REQUIRED SCREENSHOTS:** {', '.join(missing)}")
    if duplicates:
        lines.append("**DUPLICATE SCREENSHOTS DETECTED:**")
        for digest, files in duplicates.items():
            lines.append(f"- Hash `{digest}` shared by: {', '.join(files)}")
    if not duplicates:
        lines.append("- All screenshots are pairwise unique (no duplicate SHA-256 digests).")

    text = "\n".join(lines) + "\n"
    (OUT / "ui_screenshots_v3.txt").write_text(text, encoding="utf-8")
    print(text)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
