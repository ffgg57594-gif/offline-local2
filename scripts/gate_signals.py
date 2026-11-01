#!/usr/bin/env python3
"""Shared refusal-gate signal module (Stage 3.7a, measurement only).

Pure signal computation used by every later gate script. Exposes:

  load_question_sets()        -> (in_scope[60], out_of_scope[60])
  content_stems(question)     -> ordered list of unique content stems
  stem_doc_freq(stem)         -> corpus document frequency of a stem (cached)
  compute_signals(question)   -> dict with exactly s1_top1, s2_margin,
                                 s3_cov_top3, s4_unknown, s5_rare_cov_top3,
                                 n_stems, n_rare

MEASUREMENT ONLY: no thresholds, no gate_config.json, and no changes to
retrieval, fusion, embeddings, or Kotlin code. All functions are pure given
their arguments; the only global state is caches (document-frequency cache,
stem cache, and lazily opened default DB/embeddings resources), so a Kotlin
port can reimplement this module directly.

Normalization and stopword list are the same as keyword builder v2
(text_normalize.normalize_text + STOPWORDS; no document-frequency removal).
Stems are the FTS5 porter stems, queried from SQLite through a helper FTS5
table with the same tokenizer as the knowledge DB, so they are byte-identical
to the indexed terms.
"""
import json
import math
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_V3 = os.path.join("eval", "golden_v3.draft.jsonl")
GOLDEN_V2 = os.path.join("eval", "golden_v2.draft.jsonl")
NORMALIZE_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")

EXPECTED_IN_SCOPE = 60
EXPECTED_OUT_OF_SCOPE = 60
RARE_MIN_DF = 1
RARE_MAX_DF = 24  # about 2% of the ~1185 chunk corpus

# Same normalization and stopword list as keyword builder v2.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keyword_builder import STOPWORDS  # noqa: E402
from text_normalize import normalize_text  # noqa: E402

# Same FTS5 tokenizer as the knowledge DB (build_knowledge_db.py).
FTS5_TOKENIZER = "porter unicode61 remove_diacritics 2"

_TOKEN_RE = re.compile(r"\w+")

_DEFAULT_CONN = None
_DEFAULT_EMBEDDINGS = None
_DEFAULT_CHUNK_META = None
_DEFAULT_VARIANT_MAP = None
_DF_CACHE = {}      # (conn, stem) -> doc frequency
_STEM_CACHE = {}    # token -> porter stem


# ---------------------------------------------------------------------------
# Question sets
# ---------------------------------------------------------------------------

def load_question_sets():
    """Return 60 in-scope questions from golden v3 and 60 out-of-scope from
    golden v2. Fail with a clear message if counts differ from 60/60."""
    in_scope = []
    with open(GOLDEN_V3, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("in_scope") is True:
                in_scope.append({"id": obj["id"], "q": obj["q"]})

    out_of_scope = []
    with open(GOLDEN_V2, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("in_scope") is False:
                out_of_scope.append({
                    "id": obj["id"],
                    "q": obj["q"],
                    "key_terms": obj.get("key_terms") or [],
                })

    if len(in_scope) != EXPECTED_IN_SCOPE:
        raise ValueError(
            f"Expected {EXPECTED_IN_SCOPE} in-scope questions from {GOLDEN_V3} "
            f"(fields q, id), found {len(in_scope)}"
        )
    if len(out_of_scope) != EXPECTED_OUT_OF_SCOPE:
        raise ValueError(
            f"Expected {EXPECTED_OUT_OF_SCOPE} out-of-scope questions from {GOLDEN_V2} "
            f"(in_scope == false; fields q, key_terms, id), found {len(out_of_scope)}"
        )
    return in_scope, out_of_scope


# ---------------------------------------------------------------------------
# Stemming (FTS5 porter, queried from SQLite for byte-identical index terms)
# ---------------------------------------------------------------------------

def _variant_map():
    global _DEFAULT_VARIANT_MAP
    if _DEFAULT_VARIANT_MAP is None:
        _DEFAULT_VARIANT_MAP = {}
        if os.path.exists(NORMALIZE_MAP_PATH):
            with open(NORMALIZE_MAP_PATH, "r", encoding="utf-8") as f:
                _DEFAULT_VARIANT_MAP = json.load(f)
    return _DEFAULT_VARIANT_MAP


def _ensure_stem_tables(conn):
    """Create once-per-connection helper FTS5 tables for exact porter stemming."""
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS _gate_stem_helper "
        "USING fts5(x, tokenize='" + FTS5_TOKENIZER + "')"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS _gate_stem_vocab USING fts5vocab(_gate_stem_helper, 'col')"
    )


def fts_stem(token, conn):
    """Stem one token with the same FTS5 porter tokenizer as the index."""
    if token in _STEM_CACHE:
        return _STEM_CACHE[token]
    _ensure_stem_tables(conn)
    conn.execute("DELETE FROM _gate_stem_helper")
    conn.execute("INSERT INTO _gate_stem_helper(rowid, x) VALUES (1, ?)", (token,))
    row = conn.execute("SELECT term FROM _gate_stem_vocab").fetchone()
    stem = row[0] if row else token
    _STEM_CACHE[token] = stem
    return stem


def content_stems(question, conn=None):
    """Ordered unique content stems of a question.

    Normalizes like keyword builder v2 (text_normalize.normalize_text with the
    spelling-variant map), removes the same stopwords, then stems each token
    with the FTS5 porter tokenizer.
    """
    c = _default_conn() if conn is None else conn
    norm = normalize_text(question, _variant_map())
    tokens = _TOKEN_RE.findall(norm)
    stems = []
    seen = set()
    for t in tokens:
        if t in STOPWORDS:
            continue
        s = fts_stem(t, c)
        if s and s not in seen:
            seen.add(s)
            stems.append(s)
    return stems


# ---------------------------------------------------------------------------
# Document frequency (FTS5 MATCH count, cached)
# ---------------------------------------------------------------------------

def _default_conn():
    global _DEFAULT_CONN
    if _DEFAULT_CONN is None:
        _DEFAULT_CONN = sqlite3.connect(DB_PATH)
    return _DEFAULT_CONN


def stem_doc_freq(stem, conn=None):
    """Number of chunks whose search_text contains stem (FTS5 MATCH count)."""
    c = _default_conn() if conn is None else conn
    key = (id(c), stem)
    if key in _DF_CACHE:
        return _DF_CACHE[key]
    try:
        n = c.execute(
            "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
            ('"' + stem + '"',),
        ).fetchone()[0]
    except sqlite3.Error:
        n = 0
    _DF_CACHE[key] = n
    return n


def chunk_contains_stem(conn, chunk_id, stem):
    """True if chunk chunk_id's search_text contains stem (FTS5 MATCH)."""
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM chunks_fts WHERE rowid = ? AND chunks_fts MATCH ?",
            (chunk_id, '"' + stem + '"'),
        ).fetchone()[0]
    except sqlite3.Error:
        return False
    return n > 0


# ---------------------------------------------------------------------------
# Dense ranking + signals
# ---------------------------------------------------------------------------

def _cosine(a, b):
    dot = 0.0
    sa = 0.0
    sb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        sa += x * x
        sb += y * y
    na = math.sqrt(sa)
    nb = math.sqrt(sb)
    if na < 1e-12:
        na = 1e-12
    if nb < 1e-12:
        nb = 1e-12
    return dot / (na * nb)


def _load_default_embeddings_and_meta():
    global _DEFAULT_EMBEDDINGS, _DEFAULT_CHUNK_META
    if _DEFAULT_EMBEDDINGS is None:
        import numpy as np  # noqa: E402 (heavy dep; real runs only)
        with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
            meta = json.load(f)
        mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(meta["rows"], meta["dim"])
        _DEFAULT_EMBEDDINGS = mat.tolist()
        _DEFAULT_CHUNK_META = _default_conn().execute(
            "SELECT c.id, b.name, c.page, c.text FROM chunks c "
            "JOIN books b ON b.id = c.book_id ORDER BY c.id"
        ).fetchall()
    return _DEFAULT_EMBEDDINGS, _DEFAULT_CHUNK_META


def _default_embed_query(question):
    from embedding_common import embed_texts  # noqa: E402 (real runs only)
    return embed_texts([question], kind="query")[0].tolist()


def dense_top_chunks(question, embeddings, chunk_meta, embed_query, top_k=3):
    """Dense top-k chunks: (chunk_id, book, page, cosine) sorted by score desc."""
    qvec = embed_query(question)
    scores = [_cosine(qvec, row) for row in embeddings]
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:max(0, top_k)]
    out = []
    for i in order:
        row = chunk_meta[i]
        out.append((row[0], row[1], row[2], float(scores[i])))
    return out


def compute_signals(question, conn=None, embeddings=None, chunk_meta=None,
                    embed_query=None):
    """Compute the refusal-gate signals for one question.

    Returns a dict with exactly these fields:
      s1_top1       dense cosine of the top-1 chunk
      s2_margin     s1_top1 minus the cosine of the 2nd chunk
      s3_cov_top3   fraction of content stems in the top-3 chunks (0 if none)
      s4_unknown    content stems with document frequency 0
      s5_rare_cov_top3 fraction of stems with df 1..24 in the top-3 chunks
                        (-1 when the question has no such stems)
      n_stems       number of content stems
      n_rare        number of stems with document frequency 1..24
    """
    c = _default_conn() if conn is None else conn
    if embeddings is None or chunk_meta is None:
        embeddings, chunk_meta = _load_default_embeddings_and_meta()
    if embed_query is None:
        embed_query = _default_embed_query

    stems = content_stems(question, c)
    n_stems = len(stems)

    top3 = dense_top_chunks(question, embeddings, chunk_meta, embed_query, top_k=3)
    s1_top1 = top3[0][3] if top3 else 0.0
    if len(top3) > 1:
        s2_margin = s1_top1 - top3[1][3]
    else:
        s2_margin = s1_top1
    top3_cids = [r[0] for r in top3]

    s3_hits = 0
    s4_unknown = 0
    n_rare = 0
    n_rare_hits = 0
    for s in stems:
        df = stem_doc_freq(s, c)
        in_top3 = any(chunk_contains_stem(c, cid, s) for cid in top3_cids)
        if in_top3:
            s3_hits += 1
        if df == 0:
            s4_unknown += 1
        elif RARE_MIN_DF <= df <= RARE_MAX_DF:
            n_rare += 1
            if in_top3:
                n_rare_hits += 1

    if n_stems == 0:
        s3_cov_top3 = 0.0
    else:
        s3_cov_top3 = s3_hits / n_stems
    s5_rare_cov_top3 = (n_rare_hits / n_rare) if n_rare > 0 else -1.0

    return {
        "s1_top1": s1_top1,
        "s2_margin": s2_margin,
        "s3_cov_top3": s3_cov_top3,
        "s4_unknown": s4_unknown,
        "s5_rare_cov_top3": s5_rare_cov_top3,
        "n_stems": n_stems,
        "n_rare": n_rare,
    }
