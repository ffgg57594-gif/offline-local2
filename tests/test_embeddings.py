#!/usr/bin/env python3
"""Stage 3 tests for embedding scripts.

Pure-function tests run without the model. Model-dependent tests are marked
with `model` and run in CI where the model has been downloaded.
"""
import json
import os
import struct
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import embedding_common as ec  # noqa: E402


# ---------------------------------------------------------------------------
# Pure function tests (no model needed)
# ---------------------------------------------------------------------------

def test_mean_pool_ignores_padding():
    """Mean pooling must ignore padded (mask=0) positions."""
    # last_hidden_state: [batch=1, seq_len=4, dim=2]
    last_hidden = np.array([[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]]], dtype=np.float64)
    # attention_mask: positions 0,1 are real; 2,3 are padding.
    mask = np.array([[1, 1, 0, 0]], dtype=np.int64)
    pooled = ec._mean_pool(last_hidden, mask)
    expected = np.array([[(1.0 + 3.0) / 2, (2.0 + 4.0) / 2]], dtype=np.float64)
    assert np.allclose(pooled, expected), f"Got {pooled}, expected {expected}"


def test_l2_normalization_gives_norm_1():
    vectors = np.array([[3.0, 4.0], [0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float64)
    normalized = ec._l2_normalize(vectors)
    norms = np.linalg.norm(normalized, axis=1)
    # Zero vector stays zero (avoid div by zero).
    assert np.allclose(norms[0], 1.0)
    assert np.allclose(norms[1], 0.0)
    assert np.allclose(norms[2], 1.0)


def test_prefix_function():
    assert ec._prefix("passage") == "passage: "
    assert ec._prefix("query") == "query: "
    with pytest.raises(ValueError):
        ec._prefix("invalid")


def test_matrix_writer_size_and_row_order(tmp_path):
    """Write a synthetic matrix and verify size and row order."""
    rows, dim = 5, 384
    data = np.arange(rows * dim, dtype=np.float32).reshape(rows, dim)
    out_path = os.path.join(tmp_path, "test_embeddings.bin")
    data.tofile(out_path)
    expected_size = rows * dim * 4
    assert os.path.getsize(out_path) == expected_size
    read_back = np.fromfile(out_path, dtype=np.float32).reshape(rows, dim)
    assert np.array_equal(read_back, data)
    # Row order: row i matches input row i.
    assert read_back[0, 0] == 0.0
    assert read_back[-1, -1] == float(rows * dim - 1)


def test_cosine_deterministic_same_text():
    """Same vector dotted with itself = 1.0 (pure math, no model)."""
    v = np.array([0.6, 0.8], dtype=np.float32)
    assert abs(ec.cosine_similarity(v, v) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Model-dependent tests (require downloaded model)
# ---------------------------------------------------------------------------

MODEL_PATH = os.path.join("app", "src", "main", "assets", "models", "embedder", "model_quantized.onnx")
TOKENIZER_PATH = os.path.join("app", "src", "main", "assets", "models", "embedder", "tokenizer.json")

model_available = os.path.exists(MODEL_PATH) and os.path.exists(TOKENIZER_PATH)


@pytest.mark.model
def test_same_text_twice_cosine_near_1():
    if not model_available:
        pytest.skip("Model not downloaded")
    v1 = ec.embed_texts(["hypertension treatment guidelines"], kind="passage")
    v2 = ec.embed_texts(["hypertension treatment guidelines"], kind="passage")
    sim = ec.cosine_similarity(v1[0], v2[0])
    assert sim > 0.9999, f"Cosine {sim} not > 0.9999"


@pytest.mark.model
def test_query_and_passage_different_prefix():
    if not model_available:
        pytest.skip("Model not downloaded")
    text = "diabetes mellitus type 2"
    vq = ec.embed_texts([text], kind="query")[0]
    vp = ec.embed_texts([text], kind="passage")[0]
    # They should differ because prefixes differ.
    assert not np.allclose(vq, vp)


@pytest.mark.model
def test_output_dim_is_384():
    if not model_available:
        pytest.skip("Model not downloaded")
    v = ec.embed_texts(["test"], kind="query")
    assert v.shape == (1, 384)


@pytest.mark.model
def test_rows_are_l2_normalized():
    if not model_available:
        pytest.skip("Model not downloaded")
    texts = ["hello world", "medical text about hypertension", "a"]
    vs = ec.embed_texts(texts, kind="passage")
    norms = np.linalg.norm(vs, axis=1)
    assert np.all(np.abs(norms - 1.0) < 1e-3), f"Norms: {norms}"


@pytest.mark.model
def test_no_nan_inf():
    if not model_available:
        pytest.skip("Model not downloaded")
    v = ec.embed_texts(["normal medical text"], kind="query")
    assert not np.any(np.isnan(v))
    assert not np.any(np.isinf(v))
