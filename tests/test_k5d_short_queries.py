import json
import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHORT_QUERIES_PATH = ROOT / "eval/short_queries.jsonl"
REPORT_JSON_PATH = ROOT / "build/reports/k5d/short_queries_report.json"


def test_short_queries_dataset_format():
    assert SHORT_QUERIES_PATH.exists(), "eval/short_queries.jsonl must exist"
    with open(SHORT_QUERIES_PATH, "r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    assert len(rows) == 90, f"Expected 90 queries, found {len(rows)}"
    in_scope = [r for r in rows if r["in_scope"]]
    oos = [r for r in rows if not r["in_scope"]]

    assert len(in_scope) == 60, f"Expected 60 in-scope queries, got {len(in_scope)}"
    assert len(oos) == 30, f"Expected 30 out-of-scope queries, got {len(oos)}"

    for r in rows:
        words = r["q"].strip().split()
        assert 1 <= len(words) <= 4, f"Query '{r['q']}' has {len(words)} words; must be 1 to 4"

    for r in in_scope:
        assert isinstance(r["target_chunk_id"], int) and r["target_chunk_id"] > 0
        assert isinstance(r["page"], int) and r["page"] > 0


def test_short_queries_evaluation_results():
    if not REPORT_JSON_PATH.exists():
        # The evaluation needs generated assets (DB, embeddings, ONNX model)
        # that CI only builds AFTER the pytest step. Skip in that environment;
        # the CI "K5d short-query study" workflow step runs the same script
        # once the assets exist and uploads the report artifacts.
        required = [
            ROOT / "app/src/main/assets/books_knowledge.db",
            ROOT / "app/src/main/assets/embeddings.bin",
            ROOT / "app/src/main/assets/embeddings_meta.json",
            ROOT / "app/src/main/assets/models/embedder/model_quantized.onnx",
            ROOT / "app/src/main/assets/models/embedder/tokenizer.json",
        ]
        missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
        if missing:
            pytest.skip(f"generated assets missing, run scripts/evaluate_short_queries.py in CI: {missing}")
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import evaluate_short_queries
        res = evaluate_short_queries.main()
        assert res == 0

    assert REPORT_JSON_PATH.exists()
    with open(REPORT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    bal = data["balanced"]
    strict = data["strict"]
    retrieval = data["retrieval"]

    # Acceptance / rejection thresholds
    assert bal["accepted_count"] >= 55, f"Balanced accepted {bal['accepted_count']}/60"
    assert bal["oos_rejected_count"] >= 28, f"Balanced rejected OOS {bal['oos_rejected_count']}/30"

    assert strict["accepted_count"] >= 50, f"Strict accepted {strict['accepted_count']}/60"
    assert strict["oos_rejected_count"] >= 28, f"Strict rejected OOS {strict['oos_rejected_count']}/30"

    # Retrieval thresholds on same-page hit@5
    dense_same_page_5 = retrieval["dense"]["same_page"]["5"]
    assert dense_same_page_5 >= 0.80, f"Dense same-page hit@5 was {dense_same_page_5}"
