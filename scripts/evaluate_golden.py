#!/usr/bin/env python3
"""Evaluate retrieval quality on the golden question set.

Methods: dense, keyword (FTS5 bm25), fusion (RRF, fixed).
A hit = a top-k result whose page is in expected_pages.
Reports recall@1/@3/@5 and MRR, split by language (en/ar).
Lists every in-scope question that failed at top-5 with details.
Runs Arabic queries with and without alias expansion.
Prints everything to the job summary for phone review.
"""
import json
import os
import re
import sqlite3
import sys

import numpy as np

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_PATH = os.path.join("eval", "golden_questions.draft.jsonl")
ALIASES_PATH = os.path.join("app", "src", "main", "assets", "medical_aliases.json")

EMBED_DIM = 384


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat


def load_golden():
    questions = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def load_aliases():
    if not os.path.exists(ALIASES_PATH):
        return {}
    with open(ALIASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_fts_query(query):
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
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((name, page, text, float(scores[idx])))
    return results


def rrf_fuse(dense_results, fts_results, k=60, top_k=5):
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


def expand_query_arabic(query, aliases):
    """If Arabic query contains an alias key, append English terms."""
    expanded = query
    for ar_term, en_terms in aliases.items():
        if ar_term in query:
            for en in en_terms:
                if en not in expanded:
                    expanded += " " + en
    return expanded


def evaluate_questions(questions, embeddings, cur, chunk_meta, id_to_index, aliases, use_expansion):
    results = []
    for q in questions:
        query_text = q["q"]
        if q["lang"] == "ar" and use_expansion:
            query_text = expand_query_arabic(query_text, aliases)

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from embedding_common import embed_texts  # noqa: E402

        q_vec = embed_texts([query_text], kind="query")[0]

        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=5)
        fts_res = fts_search(cur, query_text, top_k=5)
        fusion_res = rrf_fuse(dense_res, fts_res, top_k=5)

        expected = set(q["expected_pages"])

        def hit_at_k(method_results, k):
            top_pages = [r[1] for r in method_results[:k]]
            return any(p in expected for p in top_pages)

        def mrr(method_results):
            for rank, r in enumerate(method_results, 1):
                if r[1] in expected:
                    return 1.0 / rank
            return 0.0

        result = {
            "q": q["q"],
            "lang": q["lang"],
            "in_scope": q["in_scope"],
            "expected_pages": sorted(expected),
            "dense_recall1": hit_at_k(dense_res, 1),
            "dense_recall3": hit_at_k(dense_res, 3),
            "dense_recall5": hit_at_k(dense_res, 5),
            "dense_mrr": mrr(dense_res),
            "keyword_recall1": hit_at_k(fts_res, 1),
            "keyword_recall3": hit_at_k(fts_res, 3),
            "keyword_recall5": hit_at_k(fts_res, 5),
            "keyword_mrr": mrr(fts_res),
            "fusion_recall1": hit_at_k(fusion_res, 1),
            "fusion_recall3": hit_at_k(fusion_res, 3),
            "fusion_recall5": hit_at_k(fusion_res, 5),
            "fusion_mrr": mrr(fusion_res),
            "dense_top3_pages": [r[1] for r in dense_res[:3]],
            "dense_top3_snippets": [centre_snippet(r[2], q["q"], 250) for r in dense_res[:3]],
            "fusion_top3_pages": [r[1] for r in fusion_res[:3]],
            "fusion_top3_snippets": [centre_snippet(r[2], q["q"], 250) for r in fusion_res[:3]],
            "query_used": query_text,
        }
        results.append(result)
    return results


def print_summary_table(results, title, label_suffix=""):
    in_scope = [r for r in results if r["in_scope"]]
    out_scope = [r for r in results if not r["in_scope"]]

    def agg(method_prefix, group):
        n = len(group)
        if n == 0:
            return (0, 0, 0, 0.0)
        r1 = sum(r[f"{method_prefix}_recall1"] for r in group) / n
        r3 = sum(r[f"{method_prefix}_recall3"] for r in group) / n
        r5 = sum(r[f"{method_prefix}_recall5"] for r in group) / n
        mrr = sum(r[f"{method_prefix}_mrr"] for r in group) / n
        return (r1, r3, r5, mrr)

    lines = [f"## {title}", "",
             "| Group | Method | N | R@1 | R@3 | R@5 | MRR |",
             "|---|---|---|---|---|---|---|"]

    for group_name, group in [("In-scope", in_scope), ("Out-of-scope", out_scope)]:
        for method in ["dense", "keyword", "fusion"]:
            r1, r3, r5, mrr = agg(method, group)
            lines.append(f"| {group_name} | {method} | {len(group)} | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} |")

    # By language for in-scope
    for lang in ["en", "ar"]:
        lang_group = [r for r in in_scope if r["lang"] == lang]
        if not lang_group:
            continue
        for method in ["dense", "keyword", "fusion"]:
            r1, r3, r5, mrr = agg(method, lang_group)
            lines.append(f"| In-scope ({lang}) | {method} | {len(lang_group)} | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} |")

    print(f"\n{title}")
    print("\n".join(lines))
    return "\n".join(lines)


def print_failed_questions(results):
    failed = [r for r in results if r["in_scope"] and r["fusion_recall5"] == 0]
    if not failed:
        print("\nAll in-scope questions retrieved at top-5 by fusion.")
        return "\nAll in-scope questions retrieved at top-5 by fusion.\n"

    lines = ["\n## Failed in-scope questions (fusion top-5 miss)", ""]
    for r in failed:
        lines.append(f"### Q: {r['q']}")
        lines.append(f"- Lang: {r['lang']}")
        lines.append(f"- Expected pages: {r['expected_pages']}")
        lines.append(f"- Dense top-3 pages: {r['dense_top3_pages']}")
        lines.append(f"- Fusion top-3 pages: {r['fusion_top3_pages']}")
        lines.append(f"- Dense snippets: {r['dense_top3_snippets']}")
        lines.append("")
    print("\n".join(lines))
    return "\n".join(lines)


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(EMBEDDINGS_BIN):
        print(f"ERROR: {EMBEDDINGS_BIN} not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(GOLDEN_PATH):
        print(f"ERROR: {GOLDEN_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    embeddings = load_embeddings()
    questions = load_golden()
    aliases = load_aliases()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    id_to_index = {cid: i for i, (cid, _, _, _) in enumerate(chunk_meta)}

    # Evaluate without expansion first.
    results_no_exp = evaluate_questions(questions, embeddings, cur, chunk_meta, id_to_index, aliases, use_expansion=False)
    # Evaluate with expansion (Arabic only affected).
    results_exp = evaluate_questions(questions, embeddings, cur, chunk_meta, id_to_index, aliases, use_expansion=True)

    summary_lines = ["# Golden Set Evaluation (DRAFT)", ""]

    summary_lines.append(print_summary_table(results_no_exp, "Retrieval Recall & MRR (no query expansion)", "no_exp"))

    # Arabic expansion comparison.
    ar_in_scope_no = [r for r in results_no_exp if r["in_scope"] and r["lang"] == "ar"]
    ar_in_scope_exp = [r for r in results_exp if r["in_scope"] and r["lang"] == "ar"]

    if ar_in_scope_no:
        lines = ["\n## Arabic Recall: With vs Without Query Expansion", "",
                 "| Metric | Without Expansion | With Expansion |",
                 "|---|---|---|"]
        for metric in ["recall1", "recall3", "recall5", "mrr"]:
            v_no = sum(r[f"fusion_{metric}"] for r in ar_in_scope_no) / len(ar_in_scope_no)
            v_exp = sum(r[f"fusion_{metric}"] for r in ar_in_scope_exp) / len(ar_in_scope_exp)
            lines.append(f"| Fusion {metric} | {v_no:.3f} | {v_exp:.3f} |")
        print("\n".join(lines))
        summary_lines.append("\n".join(lines))

    summary_lines.append(print_failed_questions(results_exp))

    # Full question list.
    lines = ["\n## Full Golden Question List", ""]
    for q in questions:
        lines.append(f"- {q['q']} (lang={q['lang']}, in_scope={q['in_scope']}, expected_pages={q['expected_pages']})")
    print("\n".join(lines))
    summary_lines.append("\n".join(lines))

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")

    conn.close()
    print("Golden evaluation complete.")


if __name__ == "__main__":
    main()
