#!/usr/bin/env python3
"""Unit tests for alias expansion and golden file parser."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from evaluate_golden import expand_query_arabic  # noqa: E402


def test_alias_expansion():
    aliases = {
        "تسمم الحمل": ["preeclampsia", "pre-eclampsia", "eclampsia"],
        "سكر الحمل": ["gestational diabetes", "GDM"],
    }
    query = "ما هي أعراض تسمم الحمل؟"
    expanded = expand_query_arabic(query, aliases)
    assert "preeclampsia" in expanded
    assert "pre-eclampsia" in expanded
    assert "eclampsia" in expanded
    assert "gestational diabetes" not in expanded


def test_alias_expansion_no_match():
    aliases = {"تسمم الحمل": ["preeclampsia"]}
    query = "كيف يتم علاج النزيف بعد الولادة؟"
    expanded = expand_query_arabic(query, aliases)
    assert expanded == query


def test_golden_parser():
    """Test parsing the golden questions JSONL file."""
    content = """{"q": "What is hypertension?", "lang": "en", "in_scope": true, "expected_pages": [10]}
{"q": "ما هي أعراض السكري؟", "lang": "ar", "in_scope": true, "expected_pages": [15]}
{"q": "what is the capital of France?", "lang": "en", "in_scope": false, "expected_pages": []}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write(content)
        tmp = f.name

    try:
        questions = []
        with open(tmp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    questions.append(json.loads(line))

        assert len(questions) == 3
        assert questions[0]["q"] == "What is hypertension?"
        assert questions[0]["lang"] == "en"
        assert questions[0]["in_scope"] is True
        assert questions[0]["expected_pages"] == [10]
        assert questions[1]["lang"] == "ar"
        assert questions[1]["expected_pages"] == [15]
        assert questions[2]["in_scope"] is False
        assert questions[2]["expected_pages"] == []
    finally:
        os.unlink(tmp)


def test_golden_required_fields():
    """Every golden question must have q, lang, in_scope, expected_pages."""
    required = {"q", "lang", "in_scope", "expected_pages"}
    with open(os.path.join(os.path.dirname(__file__), "..", "eval", "golden_questions.draft.jsonl"), "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            assert required.issubset(obj.keys()), f"Line {i} missing fields: {required - obj.keys()}"
            assert obj["lang"] in ("en", "ar"), f"Line {i}: invalid lang {obj['lang']}"
            assert isinstance(obj["in_scope"], bool), f"Line {i}: in_scope must be bool"
            assert isinstance(obj["expected_pages"], list), f"Line {i}: expected_pages must be list"
