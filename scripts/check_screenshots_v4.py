#!/usr/bin/env python3
"""Stage K7a: model download + LLM test screenshots (ui-screenshots-v4).

Verifies that the 6 required screenshots exist, computes SHA-256 digests,
ensures each screenshot is unique (fails when two files are identical — the
same image must never be reused for two state names), and prints the summary
table.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOTS = ROOT / "build/reports/k7a/ui-screenshots-v4"
OUT = ROOT / "build/reports/k7a"
REQUIRED = [
    "01_settings_model_not_installed",
    "02_settings_model_downloading",
    "03_settings_model_ready",
    "04_settings_model_error",
    "05_llm_test_streamed_output",
    "06_llm_test_stats",
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
        "directory": str(SHOTS.relative_to(ROOT)) if SHOTS.exists() else str(SHOTS),
        "files": len(rows),
        "total_bytes": total,
        "under_25mb": under_limit,
        "required": REQUIRED,
        "missing": missing,
        "duplicate_hashes": duplicates,
        "screenshots": rows,
        "status": "PASS" if ok else "FAIL",
    }
    (OUT / "ui_screenshots_v4.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "## Stage K7a: Model Settings + LLM Test Screenshots (ui-screenshots-v4)",
        "",
        f"- Files count: {len(rows)} (required: {len(REQUIRED)})",
        f"- Total size: {total} bytes",
        f"- Status: {'PASS' if ok else 'FAIL'}",
        "",
        "| Screenshot | Size (bytes) | SHA-256 | Description |",
        "|---|---|---|---|",
    ]
    descriptions = {
        "01_settings_model_not_installed.png": (
            "قسم «الموديل» في ورقة الإعدادات: كل موديلات الكتالوج بحالة «غير مثبت» "
            "مع زر التنزيل وخط الإنترنت"
        ),
        "02_settings_model_downloading.png": (
            "حالة «ينزّل الآن»: شريط تقدم بالنسبة المئوية والميجابايت وزر إلغاء التنزيل"
        ),
        "03_settings_model_ready.png": (
            "حالة «جاهز»: اسم الملف على القرص وحجمه مع زر حذف الموديل"
        ),
        "04_settings_model_error.png": (
            "حالة الخطأ «الملف غير مطابق للمتوقع» بعد رفض استيراد ملف تالف مع زر إعادة المحاولة"
        ),
        "05_llm_test_streamed_output.png": (
            "شاشة «اختبار الموديل (LLM)»: موديل محمّل، برومبت قصير، مخرجات متدفقة أثناء التوليد"
        ),
        "06_llm_test_stats.png": (
            "التشغيل المكتمل: الإحصاءات (توكنات الموجه، زمن أول توكن، توكن/ثانية، ذروة PSS، "
            "الحالة الحرارية) وزر نسخ التقرير"
        ),
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
    (OUT / "ui_screenshots_v4.txt").write_text(text, encoding="utf-8")
    print(text)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
