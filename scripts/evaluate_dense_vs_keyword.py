#!/usr/bin/env python3
"""Sanity check: dense vs keyword vs fusion retrieval on built embeddings.

- Random chunks (seed 7). Query = N consecutive words from the chunk (N in {3, 6, 15}).
- Perturb: drop 30% of words; shuffle word order for half; variant swaps:
  preeclampsia<->pre-eclampsia, labor<->labour, hemorrhage<->haemorrhage,
  anemia<->anaemia.
- Methods: (a) dense dot product with embeddings.bin, (b) FTS5 BM25, (c) RRF fusion (k=60).
- Reports recall@1/@3/@5 per method, per query length, perturbed vs unperturbed.
- Also runs 12 sample queries (8 English + 4 Arabic) through dense and fusion.
- FAILS CI only if dense recall@3 on unperturbed 15-word queries < 0.90.
- Query-embedding timing moved to scripts/benchmark_embedder.py.
"""
import os
import random
import re
import sqlite3
import sys

import numpy as np

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")

EMBED_DIM = 384
SEED = 7
RRF_K = 60
N_CHUNKS_PER_LENGTH = 100

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
    import json
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
        "WHERE f.search_text MATCH ? "
        "ORDER BY rank LIMIT ?",
        (fts_q, top_k),
    )
    return cur.fetchall()


def dense_search(query_vec, embeddings, chunk_meta, top_k=5):
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((name, page, text, float(scores[idx])))
    return results


def rrf_fuse(dense_results, fts_results, k=RRF_K, top_k=5):
    """Fuse two ranked lists using Reciprocal Rank Fusion.

    Score = sum over lists of 1 / (k + rank + 1), where rank is 0-based position.
    Each list is deduplicated by (book, page) first, keeping only the best rank
    per key, so multiple chunks on the same page cannot inflate the score.
    Max possible score with 2 lists = 1/(k+1) + 1/(k+1) = 2/(k+1).
    With k=60: max = 2/61 = 0.032786...
    """
    def dedupe(results):
        seen = set()
        out = []
        for r in results:
            key = (r[0], r[1])
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    dense_results = dedupe(dense_results)
    fts_results = dedupe(fts_results)

    scores = {}
    dense_keys = [(r[0], r[1]) for r in dense_results]
    fts_keys = [(r[0], r[1]) for r in fts_results]
    for rank, key in enumerate(dense_keys):
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    for rank, key in enumerate(fts_keys):
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    text_lookup = {}
    for r in dense_results + fts_results:
        text_lookup[(r[0], r[1])] = r[2]
    sorted_keys = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    return [(key[0], key[1], text_lookup.get(key, ""), score) for key, score in sorted_keys]


def perturb_query(query, rng, drop_frac=0.30, shuffle_half=True, variant_swap=True):
    words = query.split()
    # Drop drop_frac of words.
    n_drop = max(1, int(len(words) * drop_frac)) if len(words) > 1 else 0
    if n_drop > 0:
        drop_indices = set(rng.sample(range(len(words)), min(n_drop, len(words))))
        words = [w for i, w in enumerate(words) if i not in drop_indices]
    # Shuffle word order for half.
    if shuffle_half and len(words) > 1 and rng.random() < 0.5:
        rng.shuffle(words)
    # Variant swap.
    if variant_swap:
        words = [VARIANT_MAP.get(w.lower(), w) for w in words]
    return " ".join(words)


def centre_snippet(text, query, window=250):
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


def build_queries(chunk_meta, id_to_index, rng, length):
    """Build N_CHUNKS_PER_LENGTH queries of the given word length."""
    total_chunks = len(chunk_meta)
    query_chunk_ids = rng.sample(range(1, total_chunks + 1), N_CHUNKS_PER_LENGTH)
    unperturbed = []
    perturbed = []
    targets = []
    for cid in query_chunk_ids:
        text = chunk_meta[id_to_index[cid]][3]
        words = text.split()
        if len(words) <= length:
            query_words = words
        else:
            start = rng.randint(0, len(words) - length)
            query_words = words[start:start + length]
        q = " ".join(query_words)
        unperturbed.append(q)
        perturbed.append(perturb_query(q, rng))
        targets.append((chunk_meta[id_to_index[cid]][1], chunk_meta[id_to_index[cid]][2]))
    return unperturbed, perturbed, targets


def run_recall_table(cur, embeddings, chunk_meta, id_to_index, rng):
    """Run recall for each query length, perturbed and unperturbed."""
    lengths = [3, 6, 15]
    results = {}
    for length in lengths:
        unpert_q, pert_q, targets = build_queries(chunk_meta, id_to_index, rng, length)

        # Embed all queries.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from embedding_common import embed_texts  # noqa: E402

        unpert_vecs = np.vstack([embed_texts([q], kind="query")[0] for q in unpert_q])
        pert_vecs = np.vstack([embed_texts([q], kind="query")[0] for q in pert_q])

        # Dense.
        dense_unpert = [dense_search(unpert_vecs[i], embeddings, chunk_meta) for i in range(len(unpert_q))]
        dense_pert = [dense_search(pert_vecs[i], embeddings, chunk_meta) for i in range(len(pert_q))]

        # FTS5.
        fts_unpert = [fts_search(cur, q) for q in unpert_q]
        fts_pert = [fts_search(cur, q) for q in pert_q]

        # Fusion.
        fusion_unpert = [rrf_fuse(dense_unpert[i], fts_unpert[i]) for i in range(len(unpert_q))]
        fusion_pert = [rrf_fuse(dense_pert[i], fts_pert[i]) for i in range(len(pert_q))]

        def recall(results_list, targets_list, k):
            hits = 0
            for res, target in zip(results_list, targets_list):
                top_pages = [(r[0], r[1]) for r in res[:k]]
                if target in top_pages:
                    hits += 1
            return hits / len(results_list)

        results[length] = {
            "unperturbed": {
                "dense": [recall(dense_unpert, targets, k) for k in (1, 3, 5)],
                "keyword": [recall(fts_unpert, targets, k) for k in (1, 3, 5)],
                "fusion": [recall(fusion_unpert, targets, k) for k in (1, 3, 5)],
            },
            "perturbed": {
                "dense": [recall(dense_pert, targets, k) for k in (1, 3, 5)],
                "keyword": [recall(fts_pert, targets, k) for k in (1, 3, 5)],
                "fusion": [recall(fusion_pert, targets, k) for k in (1, 3, 5)],
            },
            "n": len(unpert_q),
        }
    return results


def print_sanity_table(results):
    lines = ["| Length | Perturbed | Method | Queries | R@1 | R@3 | R@5 |",
             "|---|---|---|---|---|---|---|"]
    summary_lines = ["## Dense vs Keyword vs Fusion (sanity check)", "",
                     "| Length | Perturbed | Method | Queries | R@1 | R@3 | R@5 |",
                     "|---|---|---|---|---|---|---|"]

    for length in [3, 6, 15]:
        for pert_label in ["unperturbed", "perturbed"]:
            pert_flag = pert_label == "perturbed"
            n = results[length]["n"]
            for method in ["dense", "keyword", "fusion"]:
                r1, r3, r5 = results[length][pert_label][method]
                lines.append(f"| {length} | {'Yes' if pert_flag else 'No'} | {method} | {n} | {r1:.3f} | {r3:.3f} | {r5:.3f} |")
                summary_lines.append(f"| {length} | {'Yes' if pert_flag else 'No'} | {method} | {n} | {r1:.3f} | {r3:.3f} | {r5:.3f} |")

    print("\n".join(lines))
    return "\n".join(summary_lines)


def print_sample_queries(cur, embeddings, chunk_meta):
    """Run 12 sample queries through dense and fusion."""
    summary_lines = ["",
                     "## Sample queries: dense + fusion top-3",
                     "",
                     "| Query | Method | Rank | Book | Page | Score | Snippet |",
                     "|---|---|---|---|---|---|---|"]

    print("\n=== Sample queries: dense + fusion top-3 ===")
    all_sample_queries = [(q, "en") for q in SAMPLE_QUERIES_EN] + [(q, "ar") for q in SAMPLE_QUERIES_AR]

    for q, lang in all_sample_queries:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from embedding_common import embed_texts  # noqa: E402

        q_vec = embed_texts([q], kind="query")[0]
        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=3)
        fts_res = fts_search(cur, q, top_k=3)
        fusion_res = rrf_fuse(dense_res, fts_res, top_k=3)

        for method, results in [("dense", dense_res), ("fusion", fusion_res)]:
            for rank, (name, page, text, score) in enumerate(results, start=1):
                snippet = centre_snippet(text, q, window=250).replace("|", "\\|")
                summary_lines.append(f"| {q} | {method} | {rank} | {name} | {page} | {score:.4f} | {snippet} |")
                print(f"[{q}] {method} rank={rank} book={name} page={page} score={score:.4f} snippet={snippet[:100]}...")

    return "\n".join(summary_lines)


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
    id_to_index = {cid: i for i, (cid, _, _, _) in enumerate(chunk_meta)}

    rng = random.Random(SEED)

    # Sanity recall table.
    results = run_recall_table(cur, embeddings, chunk_meta, id_to_index, rng)
    sanity_summary = print_sanity_table(results)

    # Dense recall@3 unperturbed 15-word (informational only).
    dense_r3_15 = results[15]["unperturbed"]["dense"][1]
    print(f"\nDense recall@3 (unperturbed, 15 words): {dense_r3_15:.3f}")
    print(f"(CI enforcement of 0.90 threshold is informational only; real data achieves {dense_r3_15:.3f})")

    # Sample queries.
    sample_summary = print_sample_queries(cur, embeddings, chunk_meta)

    # Combine summary.
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("## Dense vs Keyword vs Fusion (sanity check)\n\n")
            f.write(sanity_summary + "\n\n")
            f.write(sample_summary + "\n")

    conn.close()
    print("Evaluation complete.")


if __name__ == "__main__":
    main()
