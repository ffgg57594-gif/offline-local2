#!/usr/bin/env python3
"""K5c item 3: validate the display-only column in books_knowledge.db.

Fails when any ``display_text`` contains a private-use or unassigned code point
(or a PDF bullet glyph). Also prints how many chunks differ from the raw text.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import sqlite3
import sys
import unicodedata

DB = pathlib.Path("app/src/main/assets/books_knowledge.db")
OUT = pathlib.Path("build/reports/k5c")
# U+2022 is the replacement bullet and is allowed. These are the PDF tofu
# glyphs that must never survive in display_text.
BULLETS = {
    0x2043, 0x2219, 0x25A0, 0x25A1, 0x25AA, 0x25AB,
    0x25CF, 0x25CB, 0x25E6, 0x25FE, 0x25FD, 0x25FC, 0x25FB,
}


def bad_reason(ch: str) -> str | None:
    cp = ord(ch)
    if cp in BULLETS:
        return f"bullet U+{cp:04X}"
    category = unicodedata.category(ch)
    if category == "Co":
        return f"private-use U+{cp:04X}"
    if category == "Cn":
        return f"unassigned U+{cp:04X}"
    if category == "Cs":
        return f"surrogate U+{cp:04X}"
    return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not DB.exists():
        print(f"ERROR: missing {DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
        if "display_text" not in columns:
            print("ERROR: chunks.display_text column is missing", file=sys.stderr)
            return 1
        rows = list(conn.execute(
            "SELECT id, text, display_text FROM chunks ORDER BY id"
        ))
    finally:
        conn.close()

    changed = [cid for cid, raw, shown in rows if shown != raw]
    bad_rows = []
    for cid, raw, shown in rows:
        if shown is None:
            bad_rows.append((cid, "NULL display_text"))
            continue
        for ch in shown:
            reason = bad_reason(ch)
            if reason:
                bad_rows.append((cid, reason))
                break

    report = {
        "chunks": len(rows),
        "display_text_changed": len(changed),
        "changed_ids_sample": changed[:20],
        "bad_rows": len(bad_rows),
        "bad_sample": bad_rows[:20],
        "status": "PASS" if not bad_rows else "FAIL",
    }
    (OUT / "display_text_check.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (OUT / "display_text_check.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "text", "display_text", "changed"])
        for cid, raw, shown in rows:
            if raw != shown:
                writer.writerow([cid, raw, shown, "true"])
    lines = [
        "K5c display_text validation",
        f"chunks={len(rows)}",
        f"display_text_changed={len(changed)}",
        f"changed_ids_sample={','.join(map(str, changed[:20]))}",
        f"bad_rows={len(bad_rows)}",
        f"status={report['status']}",
    ]
    if bad_rows:
        lines.append("bad_sample=" + json.dumps(bad_rows[:20], ensure_ascii=False))
    text = "\n".join(lines) + "\n"
    (OUT / "display_text_check.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## K5c display_text validation\n\n")
            fh.write("```\n" + text + "```\n\n")
    return 0 if not bad_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
