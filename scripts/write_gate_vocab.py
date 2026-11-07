#!/usr/bin/env python3
"""Stage K4: write the Kotlin refusal-gate vocabulary from Python sources.

The Kotlin gate must reproduce ``scripts/gate_signals.py`` exactly.  To avoid a
second, hand-maintained copy of the word lists and normalization rules this
script serializes them from the Python source of truth:

  * ``keyword_builder.STOPWORDS``
  * ``keyword_builder.NON_CONTENT_WORDS``
  * ``text_normalize`` normalization constants
  * ``gate_signals.HYPHEN_COMPOUNDS`` and ``gate_signals.FTS5_TOKENIZER``
  * the CI-generated ``normalize_map.json`` (spelling variants)

Output: ``app/src/main/assets/gate_vocab.json``.

The file is generated in CI immediately after ``scripts/text_normalize.py`` and
before ``scripts/make_assets_manifest.py`` so it is covered by the APK manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate_signals import FTS5_TOKENIZER, HYPHEN_COMPOUNDS  # noqa: E402
from keyword_builder import NON_CONTENT_WORDS, STOPWORDS  # noqa: E402
from text_normalize import ZERO_WIDTH  # noqa: E402

ASSETS_DIR = os.path.join("app", "src", "main", "assets")
NORMALIZE_MAP_PATH = os.path.join(ASSETS_DIR, "normalize_map.json")
OUT_PATH = os.path.join(ASSETS_DIR, "gate_vocab.json")

# Mirrors text_normalize.normalize_text: these characters are unified to '-'.
HYPHEN_LIKE_CHARS = [
    "\u2010",  # hyphen
    "\u2011",  # non-breaking hyphen
    "\u2012",  # figure dash
    "\u2013",  # en dash
    "\u2014",  # em dash
    "\u2212",  # minus sign
]

# Python tokenizer is ``re.compile(r"\w+")`` (Unicode-aware by default).
PYTHON_TOKEN_PATTERN = r"\w+"
# Java/Kotlin equivalent compiled with Pattern.UNICODE_CHARACTER_CLASS.
KOTLIN_TOKEN_PATTERN = r"\w+"
POSSESSIVE_PATTERN = "[\x27\u2019]s\\b"


def load_variant_map(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def build_payload(variant_map: dict) -> dict:
    """Build the deterministic gate vocabulary payload."""
    return {
        "version": 1,
        "generated_by": "scripts/write_gate_vocab.py",
        "fts_tokenizer": FTS5_TOKENIZER,
        "stopwords": sorted(STOPWORDS),
        "non_content_words": sorted(NON_CONTENT_WORDS),
        "normalization": {
            "unicode_form": "NFKC",
            "zero_width_chars": [c for c in ZERO_WIDTH],
            "hyphen_like_chars": list(HYPHEN_LIKE_CHARS),
            "possessive_pattern": POSSESSIVE_PATTERN,
            "token_pattern_python": PYTHON_TOKEN_PATTERN,
            "token_pattern_kotlin": KOTLIN_TOKEN_PATTERN,
            "hyphen_compounds": {
                key: list(value)
                for key, value in sorted(HYPHEN_COMPOUNDS.items())
            },
        },
        "variant_map": {k: variant_map[k] for k in sorted(variant_map)},
    }


def write_vocab(out_path: str, variant_map_path: str) -> dict:
    variant_map = load_variant_map(variant_map_path)
    payload = build_payload(variant_map)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=OUT_PATH)
    parser.add_argument("--variant-map", default=NORMALIZE_MAP_PATH)
    args = parser.parse_args()

    if not os.path.exists(args.variant_map):
        print(
            f"ERROR: {args.variant_map} not found. Run scripts/text_normalize.py first.",
            file=sys.stderr,
        )
        return 1

    payload = write_vocab(args.out, args.variant_map)
    with open(args.out, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()

    print(f"Wrote {args.out}")
    print(f"stopwords: {len(payload['stopwords'])}")
    print(f"non_content_words: {len(payload['non_content_words'])}")
    print(f"hyphen_compounds: {len(payload['normalization']['hyphen_compounds'])}")
    print(f"variant_map: {len(payload['variant_map'])}")
    print(f"fts_tokenizer: {payload['fts_tokenizer']}")
    print(f"gate_vocab.json sha256: {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
