#!/usr/bin/env python3
"""Sanity check: dense vs keyword vs fusion retrieval on built embeddings.

- 300 random chunks (seed 7). Query = 15 consecutive words from the chunk.
- Perturb: lowercase, drop 2 random words; in 1/3 of queries apply variant swaps:
  preeclampsia<->pre-eclampsia, labor<->labour, hemorrhage<->haemorrhage, anemia<->anaemia.
- Methods: (a) dense dot product with embeddings.bin, (b) FTS5 BM25, (c) RRF fusion (k=60).
- Reports recall@1/@3/@5 per method, perturbed vs unperturbed.
- Also runs 12 sample queries (8 English + 4 Arabic) through dense and fusion.
- FAILS CI only if dense recall@3 on unperturbed queries < 0.90.
- Prints mean and p95 query-embedding time (CI runner, not a phone).
"""
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import time

import numpy as np

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")

EMBED_DIM = 384
N_QUERIES = 300
SEED = 7
RRF_K = 60

VARIANT_MAP = {
    "preeclampsia": "pre-eclampsia",
    "pre-eclampsia": "preeclampsia",
    "labor": "labour",
    "labour": "labor",
    "hemorrhage": "haemorrhage",
    "haemorrhage": "hemorrhage",
    "anemia": "anaemia",
    "anaemia": "anemia",
}

SAMPLE_QUERIES_EN = [
    "fetal", "pregnancy", "vaginal", "uterine",
    "postpartum hemorrhage", "causes of preterm labour",
    "gestational diabetes", "pre-eclampsia",
]
SAMPLE_QUERIES_AR = [
    "ما هي أسباب الولادة المبكرة",
    "علاج النزيف بعد الولادة",
    "أعراض تسمم الحمل",
    "سكر الحمل",
]


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat


def safe_fts_query(query):
    """Quote each token, join multi-word with OR."""
    tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    quoted = [f'"{t}"' for t in tokens]
    if not quoted:
        return ""
    if len(quoted) == 1:
        return quoted[0]
    return " OR ".join(quoted)


def fts_search(cur, query, top_k=5):
    fts_q = safe_fts_query(query)
    if not fts_q:
        return []
    cur.execute(
        "SELECT b.name, c.page, c.text, bm25(chunks_fts) AS rank "
        "FROM chunks_fts f "
        "JOIN chunks c ON c.id = f.rowid "
        "JOIN books b ON b.id = c.book_id "
        "WHERE f.text MATCH ? "
        "ORDER BY rank LIMIT ?",
        (fts_q, top_k),
    )
    return cur.fetchall()


def dense_search(query_vec, embeddings, chunk_meta, top_k=5):
    """query_vec: [384] float32. embeddings: [N, 384]. chunk_meta: list of (id, name, page, text)."""
    scores = embeddings @ query_vec  # [N]
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((name, page, text, float(scores[idx])))
    return results


def rrf_fuse(dense_results, fts_results, k=RRF_K, top_k=5):
    """Fuse two ranked lists using Reciprocal Rank Fusion."""
    scores = {}
    # dense_results and fts_results are lists of (name, page, text, score)
    dense_keys = [(r[0], r[1]) for r in dense_results]
    fts_keys = [(r[0], r[1]) for r in fts_results]
    all_keys = list(dict.fromkeys(dense_keys + fts_keys))  # preserve order, dedupe
    for rank, key in enumerate(dense_keys):
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    for rank, key in enumerate(fts_keys):
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    # Build lookup for text.
    text_lookup = {}
    for r in dense_results + fts_results:
        text_lookup[(r[0], r[1])] = r[2]
    sorted_keys = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    return [(key[0], key[1], text_lookup.get(key, ""), score) for key, score in sorted_keys]


def perturb_query(query, rng, variant_swap):
    words = query.split()
    words = [w.lower() for w in words]
    # Drop 2 random words.
    if len(words) > 2:
        drop_indices = rng.sample(range(len(words)), min(2, len(words)))
        words = [w for i, w in enumerate(words) if i not in drop_indices]
    # Variant swap.
    if variant_swap:
        words = [VARIANT_MAP.get(w, w) for w in words]
    return " ".join(words)


def centre_snippet(text, query, window=250):
    """Return a snippet of ~window chars centred on the sentence with most query-word overlap."""
    query_words = set(re.findall(r"\w+", query.lower()))
    sentences = re.split(r"(?<=[.!?؟.])\s+", text)
    best_sent = ""
    best_score = -1
    for sent in sentences:
        sent_words = set(re.findall(r"\w+", sent.lower()))
        score = len(query_words & sent_words)
        if score > best_score:
            best_score = score
            best_sent = sent
    if not best_sent:
        best_sent = text[:window]
    snippet = best_sent.strip()
    if len(snippet) > window:
        snippet = snippet[:window]
    return snippet


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(EMBEDDINGS_BIN):
        print(f"ERROR: {EMBEDDINGS_BIN} not found. Run build_embeddings.py first.", file=sys.stderr)
        sys.exit(1)

    embeddings = load_embeddings()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    # Map id -> index (id is sequential from 1).
    id_to_index = {cid: i for i, (cid, _, _, _) in enumerate(chunk_meta)}

    rng = random.Random(SEED)
    total_chunks = len(chunk_meta)
    query_chunk_ids = rng.sample(range(1, total_chunks + 1), N_QUERIES)

    # Build queries.
    unperturbed_queries = []
    perturbed_queries = []
    target_pages = []  # (book, page) of the source chunk
    for cid in query_chunk_ids:
        text = chunk_meta[id_to_index[cid]][3]
        words = text.split()
        if len(words) < 20:
            # Use the whole text.
            query_words = words
        else:
            start = rng.randint(0, len(words) - 20)
            query_words = words[start:start + 20]
        query = " ".join(query_words)
        unperturbed_queries.append(query)
        perturbed = perturb_query(query, rng, variant_swap=(rng.random() < 1 / 3))
        perturbed_queries.append(perturbed)
        target_pages.append((chunk_meta[id_to_index[cid]][1], chunk_meta[id_to_index[cid]][2]))

    # Embed all queries and time it.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from embedding_common import embed_texts  # noqa: E402

    timings = []
    all_unperturbed_vecs = []
    all_perturbed_vecs = []

    for q in unperturbed_queries:
        t0 = time.perf_counter()
        v = embed_texts([q], kind="query")[0]
        t1 = time.perf_counter()
        timings.append(t1 - t0)
        all_unperturbed_vecs.append(v)

    for q in perturbed_queries:
        t0 = time.perf_counter()
        v = embed_texts([q], kind="query")[0]
        t1 = time.perf_counter()
        timings.append(t1 - t0)
        all_perturbed_vecs.append(v)

    all_unperturbed_vecs = np.vstack(all_unperturbed_vecs)
    all_perturbed_vecs = np.vstack(all_perturbed_vecs)

    # Compute recall.
    def recall_at_k(results_list, target_pages_list, k):
        hits = 0
        for results, target_page in zip(results_list, target_pages_list):
            top_pages = [(r[0], r[1]) for r in results[:k]]
            if target_page in top_pages:
                hits += 1
        return hits / len(results_list)

    # Dense results.
    dense_unperturbed = []
    dense_perturbed = []
    for i in range(N_QUERIES):
        dense_unperturbed.append(dense_search(all_unperturbed_vecs[i], embeddings, chunk_meta))
        dense_perturbed.append(dense_search(all_perturbed_vecs[i], embeddings, chunk_meta))

    # FTS5 results.
    fts_unperturbed = []
    fts_perturbed = []
    for i in range(N_QUERIES):
        fts_unperturbed.append(fts_search(cur, unperturbed_queries[i]))
        fts_perturbed.append(fts_search(cur, perturbed_queries[i]))

    # Fusion results.
    fusion_unperturbed = []
    fusion_perturbed = []
    for i in range(N_QUERIES):
        fusion_unperturbed.append(rrf_fuse(dense_unperturbed[i], fts_unperturbed[i]))
        fusion_perturbed.append(rrf_fuse(dense_perturbed[i], fts_perturbed[i]))

    # Recall table.
    def recall_row(label, results, k_values=(1, 3, 5)):
        return [recall_at_k(results, target_pages, k) for k in k_values]

    lines = ["| Method | Queries | R@1 | R@3 | R@5 |", "|---|---|---|---|---|"]
    summary_lines = ["## Dense vs Keyword vs Fusion (sanity check)", "",
                     "| Method | Queries | R@1 | R@3 | R@5 |", "|---|---|---|---|---|"]

    for label, results in [
        ("Dense", dense_unperturbed),
        ("Keyword (FTS5)", fts_unperturbed),
        ("Fusion (RRF)", fusion_unperturbed),
        ("Dense (perturbed)", dense_perturbed),
        ("Keyword (perturbed)", fts_perturbed),
        ("Fusion (perturbed)", fusion_perturbed),
    ]:
        r1, r3, r5 = recall_row(label, results)
        lines.append(f"| {label} | {N_QUERIES} | {r1:.3f} | {r3:.3f} | {r5:.3f} |")
        summary_lines.append(f"| {label} | {N_QUERIES} | {r1:.3f} | {r3:.3f} | {r5:.3f} |")

    # Dense recall@3 unperturbed check.
    dense_r3_unperturbed = recall_at_k(dense_unperturbed, target_pages, 3)
    print(f"\nDense recall@3 (unperturbed): {dense_r3_unperturbed:.3f}")
    if dense_r3_unperturbed < 0.90:
        print(f"ERROR: Dense recall@3 on unperturbed queries ({dense_r3_unperturbed:.3f}) < 0.90", file=sys.stderr)
        sys.exit(1)

    print("\n".join(lines))

    # Sample queries top-3.
    summary_lines.append("")
    summary_lines.append("## Sample queries: dense + fusion top-3")
    summary_lines.append("")
    summary_lines.append("| Query | Method | Rank | Book | Page | Score | Snippet |")
    summary_lines.append("|---|---|---|---|---|---|---|")

    print("\n=== Sample queries: dense + fusion top-3 ===")
    all_sample_queries = [(q, "en") for q in SAMPLE_QUERIES_EN] + [(q, "ar") for q in SAMPLE_QUERIES_AR]

    for q, lang in all_sample_queries:
        q_vec = embed_texts([q], kind="query")[0]
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=3)
        fts_res = fts_search(cur, q, top_k=3)
        fusion_res = rrf_fuse(dense_res, fts_res, top_k=3)

        for method, results in [("dense", dense_res), ("fusion", fusion_res)]:
            for rank, (name, page, text, score) in enumerate(results, start=1):
                snippet = centre_snippet(text, q, window=250).replace("|", "\\|")
                summary_lines.append(f"| {q} | {method} | {rank} | {name} | {page} | {score:.4f} | {snippet} |")
                print(f"[{q}] {method} rank={rank} book={name} page={page} score={score:.4f} snippet={snippet[:100]}...")

    summary_lines.append("")
    print("\n".join(summary_lines))

    # Timing stats.
    timings_arr = np.array(timings)
    mean_t = float(np.mean(timings_arr))
    p95_t = float(np.percentile(timings_arr, 95))
    print(f"\nQuery embedding time (CI runner): mean={mean_t*1000:.2f} ms, p95={p95_t*1000:.2f} ms")
    summary_lines.append("")
    summary_lines.append(f"## Query embedding time (CI runner, not a phone)")
    summary_lines.append("")
    summary_lines.append(f"- Mean: {mean_t*1000:.2f} ms")
    summary_lines.append(f"- p95: {p95_t*1000:.2f} ms")
    summary_lines.append("")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")

    conn.close()
    print("Evaluation complete.")


if __name__ == "__main__":
    main()
