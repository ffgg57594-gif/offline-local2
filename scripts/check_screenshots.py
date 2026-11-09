#!/usr/bin/env python3
"""K5c screenshot acceptance: unique PNGs, sha256 table, under 25 MiB.

Fails when a required state is missing or when two files are byte-identical
(the same image must never be reused for two state names).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOTS = ROOT / "build/reports/k5b/ui-screenshots"
OUT = ROOT / "build/reports/k5c"
REQUIRED = [
    "01_empty_light",
    "02_empty_dark",
    "03_results_light_keyboard_closed",
    "04_results_dark_keyboard_closed",
    "05_results_font13_dark",
    "06_sheet_top_light",
    "07_sheet_bottom_light",
    "08_sheet_top_font13_light",
    "09_sheet_bottom_font13_light",
    "10_refusal_collapsed_light",
    "11_refusal_expanded_light",
    "12_loading_searching_light",
    "13_settings_strict_light",
    "14_long_english_passage_light",
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
    pngs = sorted(SHOTS.glob("*.png")) if SHOTS.exists() else []
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
        "directory": str(SHOTS.relative_to(ROOT)),
        "files": len(rows),
        "total_bytes": total,
        "under_25mb": under_limit,
        "required": REQUIRED,
        "missing": missing,
        "duplicate_hashes": duplicates,
        "screenshots": rows,
        "status": "PASS" if ok else "FAIL",
    }
    (OUT / "screenshot_hashes.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = ["K5c screenshot check", f"files={len(rows)}", f"total_bytes={total}"]
    for row in rows:
        lines.append(f"{row['sha256']}  {row['file']}  ({row['bytes']} bytes)")
    lines.append(f"required_missing={','.join(missing) if missing else 'none'}")
    if duplicates:
        for digest, files in duplicates.items():
            lines.append(f"DUPLICATE {digest}: {', '.join(files)}")
    else:
        lines.append("duplicates=none")
    lines.append(f"under_25mb={'YES' if under_limit else 'NO'}")
    lines.append(f"status={report['status']}")
    text = "\n".join(lines) + "\n"
    (OUT / "screenshot_hashes.txt").write_text(text, encoding="utf-8")
    print(text, end="")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## K5c screenshot hashes\n\n")
            fh.write("```\n" + text + "```\n\n")

    # STAGE UI-A: Design Gallery verification
    gallery_script = ROOT / "scripts/check_gallery_screenshots.py"
    gallery_ok = True
    if gallery_script.exists():
        import check_gallery_screenshots
        gallery_code = check_gallery_screenshots.main()
        gallery_ok = (gallery_code == 0)

    # STAGE K5d: Real-keyboard screenshots verification (ui-screenshots-v3)
    v3_script = ROOT / "scripts/check_screenshots_v3.py"
    v3_ok = True
    if v3_script.exists():
        import check_screenshots_v3
        v3_code = check_screenshots_v3.main()
        v3_ok = (v3_code == 0)

    return 0 if (ok and gallery_ok and v3_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
