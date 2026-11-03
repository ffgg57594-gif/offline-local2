import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from gate_signals import content_stems, load_question_sets
from gate_rule import accept
from fit_gate import load_labeled_signals, fit_preset, CONFIG_OUT, REFERENCE_OUT


def test_loader_with_label_fixes():
    in_scope, out_of_scope = load_question_sets()
    assert len(in_scope) == 60
    assert len(out_of_scope) == 60

    fixes_path = os.path.join("eval", "label_fixes.json")
    assert os.path.exists(fixes_path)
    with open(fixes_path, "r", encoding="utf-8") as f:
        fixes = json.load(f)["fixes"]
    fixed_ids = {f["id"] for f in fixes if f["action"] == "answered_by_book"}
    assert fixed_ids == {26, 29, 48}

    # Verify counts when fixes applied
    ans = list(in_scope)
    oos = []
    cls_counts = {"A": 0, "B": 0, "N": 0}
    for q in out_of_scope:
        if q["id"] in fixed_ids:
            ans.append(q)
        else:
            oos.append(q)
            c = q.get("cls")
            if c in cls_counts:
                cls_counts[c] += 1

    assert len(ans) == 63
    assert len(oos) == 57
    assert cls_counts == {"A": 24, "B": 21, "N": 12}


def test_hyphen_fix_three_words():
    stems_unhyphenated = content_stems("vesicovaginal")
    stems_hyphenated = content_stems("vesico-vaginal")
    stems_tension = content_stems("tension-free")

    assert stems_unhyphenated == ["vesico", "vagin"]
    assert stems_hyphenated == ["vesico", "vagin"]
    assert stems_unhyphenated == stems_hyphenated
    assert stems_tension == ["tension", "free"]


def test_hyphen_fix_bidirectional_and_compounds():
    # Bidirectional matching
    assert content_stems("tensionfree") == ["tension", "free"]
    assert content_stems("tension-free") == ["tension", "free"]
    assert content_stems("vesico-vaginal fistula") == ["vesico", "vagin", "fistula"]
    assert content_stems("vesicovaginal fistula") == ["vesico", "vagin", "fistula"]


def test_hyphen_fix_does_not_break_single_words():
    # Regular medical words should not be altered
    assert content_stems("pregnancy") == ["pregnanc"]
    assert content_stems("preeclampsia") == ["preeclampsia"]
    assert content_stems("eclampsia") == ["eclampsia"]


def test_gate_rule_pure_function():
    params = {"t1": 0.84, "t3": 0.571429, "k": 0}
    assert accept(0.85, 0.60, 0, params) is True
    assert accept(0.83, 0.60, 0, params) is False  # s1 too low
    assert accept(0.85, 0.50, 0, params) is False  # s3 too low
    assert accept(0.85, 0.60, 1, params) is False  # s4 too high


def test_gate_config_and_reference_exist():
    assert os.path.exists(CONFIG_OUT)
    assert os.path.exists(REFERENCE_OUT)

    with open(CONFIG_OUT, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg["version"] == 1
    assert "balanced" in cfg and "strict" in cfg
    for p in ["balanced", "strict"]:
        assert "t1" in cfg[p]
        assert "t3" in cfg[p]
        assert "k" in cfg[p]

    with open(REFERENCE_OUT, "r", encoding="utf-8") as f:
        ref = json.load(f)
    assert len(ref) == 120
    for item in ref:
        assert "signals" in item
        assert "decisions" in item
        assert "balanced" in item["decisions"]
        assert "strict" in item["decisions"]
