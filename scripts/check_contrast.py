#!/usr/bin/env python3
"""K5c item 10: WCAG AA contrast for the dark highlight and citation chip.

The colours are read from the same Kotlin object the Compose theme uses, so
this check cannot drift from the shipped UI. It prints the computed ratios and
fails when either text/background pair is below 4.5:1.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLORS_KT = ROOT / "app/src/main/java/com/medai/assistant/ui/UiColors.kt"
OUT = ROOT / "build/reports/k5c"
PAIRS = [
    ("highlight", "HIGHLIGHT_BACKGROUND_DARK", "HIGHLIGHT_TEXT_DARK"),
    ("citation_chip", "CITATION_CHIP_BACKGROUND_DARK", "CITATION_CHIP_TEXT_DARK"),
]


def read_colors() -> dict[str, int]:
    text = COLORS_KT.read_text(encoding="utf-8")
    values: dict[str, int] = {}
    for name, hex_value in re.findall(
        r"const\s+val\s+([A-Z0-9_]+)\s*=\s*0x([0-9A-Fa-f]{8})", text
    ):
        values[name] = int(hex_value, 16)
    return values


def channel(value: int) -> float:
    srgb = value / 255.0
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def luminance(rgb: int) -> float:
    r = (rgb >> 16) & 0xFF
    g = (rgb >> 8) & 0xFF
    b = rgb & 0xFF
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: int, b: int) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    colors = read_colors()
    missing = [
        name
        for _, bg, fg in PAIRS
        for name in (bg, fg)
        if name not in colors
    ]
    if missing:
        print(f"ERROR: missing colour constants: {', '.join(missing)}", file=sys.stderr)
        return 1

    rows = []
    ok = True
    for label, bg_name, fg_name in PAIRS:
        bg, fg = colors[bg_name], colors[fg_name]
        ratio = contrast(bg, fg)
        passed = ratio >= 4.5
        ok = ok and passed
        rows.append(
            {
                "pair": label,
                "background": f"#{bg & 0xFFFFFF:06X}",
                "text": f"#{fg & 0xFFFFFF:06X}",
                "contrast_ratio": round(ratio, 3),
                "wcag_aa": passed,
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "contrast_dark.json").write_text(
        json.dumps({"pairs": rows, "status": "PASS" if ok else "FAIL"}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    lines = ["K5c dark-theme contrast (WCAG AA text requires 4.5:1)"]
    for row in rows:
        lines.append(
            f"{row['pair']}: bg={row['background']} text={row['text']} "
            f"ratio={row['contrast_ratio']:.3f} "
            f"{'PASS' if row['wcag_aa'] else 'FAIL'}"
        )
    lines.append(f"status={'PASS' if ok else 'FAIL'}")
    text = "\n".join(lines) + "\n"
    (OUT / "contrast_dark.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## K5c dark theme contrast\n\n")
            fh.write("```\n" + text + "```\n\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
