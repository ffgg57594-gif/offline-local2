#!/usr/bin/env python3
"""Shared embedding module for multilingual-e5-small quantized ONNX.

Provides embed_texts(texts, kind) used by every script that embeds text.
kind is "passage" or "query"; the corresponding prefix is prepended.
Tokenization: truncation max_length=384, padding per batch, attention mask.
Pooling: mean pooling over the attention mask, then L2 normalization.
Output dim is 384 (asserted). Batch size 16. Deterministic.
"""
import json
import os
from typing import List

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = os.path.join("app", "src", "main", "assets", "models", "embedder")
MODEL_PATH = os.path.join(MODEL_DIR, "model_quantized.onnx")
TOKENIZER_PATH = os.path.join(MODEL_DIR, "tokenizer.json")

MAX_LENGTH = 384
EMBED_DIM = 384
BATCH_SIZE = 16

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

_session: ort.InferenceSession | None = None
_tokenizer: Tokenizer | None = None


def _load():
    global _session, _tokenizer
    if _session is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")
        if not os.path.exists(TOKENIZER_PATH):
            raise FileNotFoundError(f"Tokenizer file not found: {TOKENIZER_PATH}")
        _session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
        _tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
    return _session, _tokenizer


def _prefix(kind: str) -> str:
    if kind == "passage":
        return PASSAGE_PREFIX
    if kind == "query":
        return QUERY_PREFIX
    raise ValueError(f"kind must be 'passage' or 'query', got {kind!r}")


def _tokenize_batch(tokenizer: Tokenizer, texts: List[str]):
    """Tokenize a batch with truncation to MAX_LENGTH and padding to the longest in batch.
    Returns (input_ids, attention_mask) as numpy int64 arrays of shape [batch, seq_len].
    """
    encodings = tokenizer.encode_batch(texts)
    max_len = min(MAX_LENGTH, max(len(e.ids) for e in encodings))
    input_ids = []
    attention_masks = []
    for enc in encodings:
        ids = enc.ids[:max_len]
        mask = [1] * len(ids)
        pad_len = max_len - len(ids)
        ids += [0] * pad_len
        mask += [0] * pad_len
        input_ids.append(ids)
        attention_masks.append(mask)
    return np.array(input_ids, dtype=np.int64), np.array(attention_masks, dtype=np.int64)


def _mean_pool(last_hidden_state: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Mean pooling over the attention mask.
    last_hidden_state: [batch, seq_len, dim]
    attention_mask: [batch, seq_len]
    Returns: [batch, dim]
    """
    mask = attention_mask.astype(np.float64)  # [batch, seq_len]
    mask_sum = np.sum(mask, axis=1, keepdims=True)  # [batch, 1]
    mask_sum = np.clip(mask_sum, 1e-9, None)  # avoid div by zero
    masked = last_hidden_state.astype(np.float64) * mask[:, :, None]  # [batch, seq_len, dim]
    pooled = np.sum(masked, axis=1) / mask_sum  # [batch, dim]
    return pooled


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.clip(norms, 1e-12, None)
    return vectors / norms


def embed_texts(texts: List[str], kind: str) -> np.ndarray:
    """Embed a list of texts.

    Args:
        texts: list of raw text strings (no prefix).
        kind: "passage" or "query" — selects the prefix.

    Returns:
        numpy array of shape [len(texts), 384], float32, L2-normalized.
    """
    session, tokenizer = _load()
    prefix = _prefix(kind)
    prefixed = [prefix + t for t in texts]

    all_embeddings = []
    for start in range(0, len(prefixed), BATCH_SIZE):
        batch = prefixed[start:start + BATCH_SIZE]
        input_ids, attention_mask = _tokenize_batch(tokenizer, batch)
        outputs = session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                # token_type_ids not used by e5; provide zeros if the model expects it.
            },
        )
        # The model output is typically [batch, seq_len, dim] as the first output.
        last_hidden_state = outputs[0]
        pooled = _mean_pool(last_hidden_state, attention_mask)
        normalized = _l2_normalize(pooled)
        all_embeddings.append(normalized.astype(np.float32))

    result = np.vstack(all_embeddings) if all_embeddings else np.empty((0, EMBED_DIM), dtype=np.float32)
    assert result.shape[1] == EMBED_DIM, f"Expected embedding dim {EMBED_DIM}, got {result.shape[1]}"
    return result


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors (already L2-normalized -> dot product)."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
