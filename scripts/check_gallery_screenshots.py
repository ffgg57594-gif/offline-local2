#!/usr/bin/env python3
"""STAGE UI-A: Verifies design-gallery screenshots:
- Unique file names
- Computes sha256 of every PNG
- Fails if two images are byte-identical
- Verifies total size is under 25 MB
- Prints the sha256 table and total size
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOTS = ROOT / "build/reports/design-gallery"
OUT = ROOT / "build/reports/design-gallery"
MAX_BYTES = 25 * 1024 * 1024

REQUIRED_GROUPS = [
    "cards",
    "citation_bubbles",
    "refusal_empty",
    "input_progress",
    "sheet",
    "topbar",
]


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pngs = sorted(SHOTS.glob("*.png")) if SHOTS.exists() else []

    if not pngs:
        print(f"ERROR: No design-gallery screenshots found in {SHOTS}", file=sys.stderr)
        return 1

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

    # Check for duplicate hashes (fails if two are identical)
    duplicates = {
        digest: files for digest, files in by_hash.items() if len(files) > 1
    }

    # Check that both directions (a and b) and all 6 groups are represented
    filenames = [r["file"] for r in rows]
    missing_groups_a = [g for g in REQUIRED_GROUPS if not any(f.startswith("gallery_a_") and g in f for f in filenames)]
    missing_groups_b = [g for g in REQUIRED_GROUPS if not any(f.startswith("gallery_b_") and g in f for f in filenames)]

    total_bytes = sum(r["bytes"] for r in rows)
    under_limit = total_bytes < MAX_BYTES

    ok = (not duplicates) and under_limit and (not missing_groups_a) and (not missing_groups_b)

    report = {
        "directory": str(SHOTS.relative_to(ROOT)),
        "files_count": len(rows),
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "under_25mb": under_limit,
        "missing_groups_a": missing_groups_a,
        "missing_groups_b": missing_groups_b,
        "duplicates": duplicates,
        "screenshots": rows,
        "status": "PASS" if ok else "FAIL",
    }

    (OUT / "gallery_summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print("=" * 72)
    print("STAGE UI-A: DESIGN GALLERY SCREENSHOT CHECK")
    print(f"Total screenshots: {len(rows)}")
    print(f"Total size: {total_bytes} bytes ({report['total_mb']} MB) — Under 25 MB: {'YES' if under_limit else 'NO'}")
    print("-" * 72)
    for r in rows:
        print(f"{r['sha256']}  {r['file']}  ({r['bytes']:,} bytes)")
    print("-" * 72)

    if duplicates:
        print("FAIL: Duplicate identical screenshots detected:", file=sys.stderr)
        for digest, files in duplicates.items():
            print(f"  SHA256 {digest}: {', '.join(files)}", file=sys.stderr)
    else:
        print("PASS: All screenshot SHA256 hashes are strictly unique.")

    if missing_groups_a:
        print(f"FAIL: Missing component groups for Direction A: {missing_groups_a}", file=sys.stderr)
    if missing_groups_b:
        print(f"FAIL: Missing component groups for Direction B: {missing_groups_b}", file=sys.stderr)

    if not under_limit:
        print(f"FAIL: Total gallery size ({total_bytes} bytes) exceeds 25 MB limit!", file=sys.stderr)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as sf:
            sf.write("### STAGE UI-A: Design Gallery Screenshots\n\n")
            sf.write(f"- **Files**: {len(rows)}\n")
            sf.write(f"- **Total Size**: {total_bytes:,} bytes ({report['total_mb']} MB)\n")
            sf.write(f"- **Status**: {'PASS' if ok else 'FAIL'}\n\n")
            sf.write("| File | Size (bytes) | SHA-256 |\n|---|---|---|\n")
            for r in rows:
                sf.write(f"| `{r['file']}` | {r['bytes']:,} | `{r['sha256']}` |\n")
            sf.write("\n")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
