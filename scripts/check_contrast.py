#!/usr/bin/env python3
"""Stage UI-A & K5c: WCAG AA contrast check for all design tokens.

Validates:
- Direction A ("ورق وحبر" / Paper & Ink): Light and Dark palettes.
- Direction B ("ليل سريري" / Clinical Night): Light and Dark palettes.
- K5c pinned tokens.
Fails if any text pair is below 4.5:1 (or large text / icon below 3.0:1).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLORS_KT = ROOT / "app/src/main/java/com/medai/assistant/ui/UiColors.kt"
TOKENS_KT = ROOT / "app/src/main/java/com/medai/assistant/design/DesignTokens.kt"
OUT = ROOT / "build/reports/k5c"

# Backward compatibility pairs from UiColors.kt
K5C_PAIRS = [
    ("highlight", "HIGHLIGHT_BACKGROUND_DARK", "HIGHLIGHT_TEXT_DARK", 4.5),
    ("citation_chip", "CITATION_CHIP_BACKGROUND_DARK", "CITATION_CHIP_TEXT_DARK", 4.5),
]

# STAGE UI-A Design Tokens for Direction A & B
DESIGN_PAIRS = [
    # Direction A: "ورق وحبر" (Light)
    ("A_LIGHT", "Background & Ink Body", "#F7F4EE", "#1B2024", 4.5),
    ("A_LIGHT", "Background & Secondary Text", "#F7F4EE", "#424D53", 4.5),
    ("A_LIGHT", "Card Surface & Ink Body", "#EFECE4", "#1B2024", 4.5),
    ("A_LIGHT", "Card Surface & Secondary Text", "#EFECE4", "#424D53", 4.5),
    ("A_LIGHT", "Primary Accent (Teal) & White", "#0F5C5C", "#FFFFFF", 4.5),
    ("A_LIGHT", "PrimaryContainer & onContainer", "#D2E8E7", "#063636", 4.5),
    ("A_LIGHT", "Marker Highlight (Amber) & Ink", "#F8E4B3", "#1B2024", 4.5),
    ("A_LIGHT", "Bookmark Tab & Text", "#DDEBE9", "#0B4B4B", 4.5),
    ("A_LIGHT", "Refusal/Error & White", "#BA3D2A", "#FFFFFF", 4.5),

    # Direction A: "ورق وحبر" (Dark)
    ("A_DARK", "Warm Charcoal BG & Body Text", "#1B1D1E", "#F3EFE7", 4.5),
    ("A_DARK", "Warm Charcoal BG & Secondary Text", "#1B1D1E", "#B8B3A7", 4.5),
    ("A_DARK", "Dark Card Surface & Body Text", "#2B2E2F", "#F3EFE7", 4.5),
    ("A_DARK", "Dark Card Surface & Secondary Text", "#2B2E2F", "#B8B3A7", 4.5),
    ("A_DARK", "Primary Accent & onPrimary", "#62B8B8", "#003737", 4.5),
    ("A_DARK", "PrimaryContainer & onContainer", "#144D4D", "#BDE8E8", 4.5),
    ("A_DARK", "Dark Amber Marker & Highlight Text", "#4E3E18", "#FFE8B3", 4.5),
    ("A_DARK", "Bookmark Tab & Text", "#194545", "#BDE8E8", 4.5),
    ("A_DARK", "Refusal/Error & onError", "#FFB4A9", "#690005", 4.5),

    # Direction B: "ليل سريري" (Light)
    ("B_LIGHT", "Near-White BG & Deep Navy Body", "#F4F7F9", "#0E161C", 4.5),
    ("B_LIGHT", "Near-White BG & Secondary Text", "#F4F7F9", "#3B4851", 4.5),
    ("B_LIGHT", "Clinical Card & Deep Navy Body", "#E9EFF3", "#0E161C", 4.5),
    ("B_LIGHT", "Clinical Card & Secondary Text", "#E9EFF3", "#3B4851", 4.5),
    ("B_LIGHT", "Medical Green & White", "#006A5E", "#FFFFFF", 4.5),
    ("B_LIGHT", "PrimaryContainer & onContainer", "#9EF2E2", "#00201B", 4.5),
    ("B_LIGHT", "Cyan-Green Marker & Text", "#C9EFE8", "#003730", 4.5),
    ("B_LIGHT", "Bookmark Tab & Text", "#D3EEF1", "#004953", 4.5),
    ("B_LIGHT", "Coral Alert & White", "#BA3826", "#FFFFFF", 4.5),

    # Direction B: "ليل سريري" (Dark)
    ("B_DARK", "Ink-Navy BG & Ice Body", "#0E1417", "#EEF3F6", 4.5),
    ("B_DARK", "Ink-Navy BG & Secondary Text", "#0E1417", "#9EADB7", 4.5),
    ("B_DARK", "Navy Card Surface & Ice Body", "#1B2328", "#EEF3F6", 4.5),
    ("B_DARK", "Navy Card Surface & Secondary Text", "#1B2328", "#9EADB7", 4.5),
    ("B_DARK", "Cyan-Teal & onPrimary", "#53DBC7", "#003730", 4.5),
    ("B_DARK", "PrimaryContainer & onContainer", "#005047", "#73F8E3", 4.5),
    ("B_DARK", "Dark Cyan Marker & Text", "#0F4640", "#A2F5E7", 4.5),
    ("B_DARK", "Bookmark Tab & Text", "#103E48", "#A3E5F3", 4.5),
    ("B_DARK", "Coral Alert & onError", "#FFB4A9", "#690005", 4.5),
]


def read_ui_colors() -> dict[str, int]:
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


def luminance_rgb(r: int, g: int, b: int) -> float:
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def luminance_hex(hex_str: str) -> float:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return luminance_rgb(r, g, b)


def contrast(l1: float, l2: float) -> float:
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    colors = read_ui_colors()
    missing = [
        name
        for _, bg, fg, _ in K5C_PAIRS
        for name in (bg, fg)
        if name not in colors
    ]
    if missing:
        print(f"ERROR: missing colour constants: {', '.join(missing)}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    all_ok = True

    # 1. K5c backwards-compatible check
    k5c_rows = []
    for label, bg_name, fg_name, req in K5C_PAIRS:
        bg_int, fg_int = colors[bg_name], colors[fg_name]
        l_bg = luminance_rgb((bg_int >> 16) & 0xFF, (bg_int >> 8) & 0xFF, bg_int & 0xFF)
        l_fg = luminance_rgb((fg_int >> 16) & 0xFF, (fg_int >> 8) & 0xFF, fg_int & 0xFF)
        ratio = contrast(l_bg, l_fg)
        passed = ratio >= req
        all_ok = all_ok and passed
        k5c_rows.append(
            {
                "pair": label,
                "background": f"#{bg_int & 0xFFFFFF:06X}",
                "text": f"#{fg_int & 0xFFFFFF:06X}",
                "contrast_ratio": round(ratio, 3),
                "wcag_aa": passed,
            }
        )

    (OUT / "contrast_dark.json").write_text(
        json.dumps({"pairs": k5c_rows, "status": "PASS" if all_ok else "FAIL"}, indent=2) + "\n",
        encoding="utf-8",
    )
    lines_k5c = ["K5c dark-theme contrast (WCAG AA text requires 4.5:1)"]
    for row in k5c_rows:
        lines_k5c.append(
            f"{row['pair']}: bg={row['background']} text={row['text']} "
            f"ratio={row['contrast_ratio']:.3f} "
            f"{'PASS' if row['wcag_aa'] else 'FAIL'}"
        )
    lines_k5c.append(f"status={'PASS' if all_ok else 'FAIL'}")
    text_k5c = "\n".join(lines_k5c) + "\n"
    (OUT / "contrast_dark.txt").write_text(text_k5c, encoding="utf-8")

    # 2. STAGE UI-A Design Tokens Check
    design_rows = []
    for group, label, bg_hex, fg_hex, req in DESIGN_PAIRS:
        l_bg = luminance_hex(bg_hex)
        l_fg = luminance_hex(fg_hex)
        ratio = contrast(l_bg, l_fg)
        passed = ratio >= req
        all_ok = all_ok and passed
        design_rows.append(
            {
                "group": group,
                "label": label,
                "background": bg_hex,
                "text": fg_hex,
                "contrast_ratio": round(ratio, 2),
                "required": req,
                "wcag_aa": passed,
            }
        )

    (OUT / "contrast_stage_ui_a.json").write_text(
        json.dumps({"pairs": design_rows, "status": "PASS" if all_ok else "FAIL"}, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 84)
    print("STAGE UI-A: WCAG AA CONTRAST RATIO AUDIT TABLE")
    print("=" * 84)
    print(f"{'Group':<10} {'Element Pair':<36} {'BG':<9} {'FG':<9} {'Ratio':<10} {'WCAG AA'}")
    print("-" * 84)
    for r in design_rows:
        status = "PASS" if r["wcag_aa"] else "FAIL"
        print(f"{r['group']:<10} {r['label']:<36} {r['background']:<9} {r['text']:<9} {r['contrast_ratio']:>5.2f}:1    [{status}]")
    print("=" * 84)
    print(f"Overall Contrast Status: {'PASS' if all_ok else 'FAIL'}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## STAGE UI-A: Design Tokens WCAG AA Contrast Audit\n\n")
            fh.write("| Group | Element Pair | Background | Text | Contrast Ratio | WCAG AA |\n")
            fh.write("|---|---|---|---|---|---|\n")
            for r in design_rows:
                fh.write(
                    f"| {r['group']} | {r['label']} | `{r['background']}` | `{r['text']}` | **{r['contrast_ratio']:.2f}:1** | {'PASS' if r['wcag_aa'] else 'FAIL'} |\n"
                )
            fh.write("\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
