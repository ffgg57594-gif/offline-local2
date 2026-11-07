#!/usr/bin/env python3
"""Stage K4: tests for the CI-generated Kotlin gate vocabulary."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from write_gate_vocab import build_payload, write_vocab  # noqa: E402


def _variant_map_file(tmp_path):
    path = tmp_path / "normalize_map.json"
    path.write_text(
        json.dumps({"labour": "labor", "tumour": "tumor"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(path)


def test_payload_contains_python_sources(tmp_path):
    payload = build_payload({"labour": "labor", "tumour": "tumor"})

    assert payload["fts_tokenizer"] == "porter unicode61 remove_diacritics 2"

    stopwords = set(payload["stopwords"])
    assert len(stopwords) >= 150
    assert "the" in stopwords
    assert "what" in stopwords
    # "pregnancy" is a medical content word and must not be a stopword.
    assert "pregnancy" not in stopwords

    non_content = payload["non_content_words"]
    assert len(non_content) <= 40
    assert "patient" in non_content

    norm = payload["normalization"]
    assert norm["unicode_form"] == "NFKC"
    assert "\u200b" in norm["zero_width_chars"]
    assert "\u2013" in norm["hyphen_like_chars"]
    assert norm["possessive_pattern"] == "[\x27\u2019]s\\b"
    assert norm["token_pattern_python"] == r"\w+"
    # Android's ICU regex engine rejects the JVM-only Unicode flag, so the
    # Kotlin side spells the classes out (see Patterns.kt).
    assert norm["token_pattern_kotlin"] == r"[\p{L}\p{M}\p{N}_]+"

    assert norm["hyphen_compounds"]["vesicovaginal"] == ["vesico", "vaginal"]
    assert norm["hyphen_compounds"]["vesico-vaginal"] == ["vesico", "vaginal"]
    assert norm["hyphen_compounds"]["tensionfree"] == ["tension", "free"]
    assert norm["hyphen_compounds"]["tension-free"] == ["tension", "free"]

    assert payload["variant_map"] == {"labour": "labor", "tumour": "tumor"}


def test_written_file_is_deterministic_and_utf8(tmp_path):
    variant_path = _variant_map_file(tmp_path)
    out1 = str(tmp_path / "gate_vocab_1.json")
    out2 = str(tmp_path / "gate_vocab_2.json")

    payload = write_vocab(out1, variant_path)
    write_vocab(out2, variant_path)

    with open(out1, "rb") as f:
        bytes1 = f.read()
    with open(out2, "rb") as f:
        bytes2 = f.read()
    assert bytes1 == bytes2
    assert bytes1.endswith(b"\n")

    data = json.loads(bytes1.decode("utf-8"))
    assert data["stopwords"] == sorted(data["stopwords"])
    assert data["variant_map"] == {"labour": "labor", "tumour": "tumor"}
    assert data == payload
