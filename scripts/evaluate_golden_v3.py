#!/usr/bin/env python3
"""Re-measurement on golden v3 (chunk-level labels) with bias audits.

Methods: dense, keyword (v1-v4), weighted RRF fusion with grid k in {10, 60}
x w_kw in {0, 0.25, 0.5, 1.0}, candidate pools of top-20 per list.

Hit definitions:
  STRICT hit at k   = target_chunk_id or any alt_chunk_id is in top-k chunks.
  TARGET-ONLY hit k = target_chunk_id only (no alt_chunk_ids).
  LENIENT hit at k  = STRICT or a chunk adjacent (id +/- 1 in same book,
                      same page) is in top-k chunks.
  MRR               = mean over ALL questions of 1/rank of the first hit
                      within top-10, and 0 when there is no hit.
  Page de-duplication is NOT applied before measuring.

Reports Table 1 (dense + keyword v1-v4, STRICT and LENIENT) and
Table 2 (5-fold CV, all 8 fusion configs, per-fold and mean+/-std, STRICT).

Chooses w_kw > 0 only if mean STRICT hit@3 beats w_kw=0 by >= 0.03;
otherwise keeps w_kw=0. Writes assets/fusion_config.json.

Bias table: STRICT vs TARGET-ONLY, by lexical-overlap group (<=1, 2-3, >=4),
for dense and fused (chosen config), with counts and hit@1/3/5/MRR@10.
Alternates audit: per-question alt id, page, 200-char snippet, source.
Golden v3 full listing with overlap per question. Out-of-scope rows with
FTS match counts per key term. Failure review under chosen config.
sha256 check: database chunk-text hash vs embeddings_meta.json.
"""
import hashlib
import json
import os
import random
import re
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedding_common import embed_texts  # noqa: E402
from text_normalize import normalize_text, load_variant_map  # noqa: E402
from keyword_builder import (  # noqa: E402
    build_keyword_query,
    fts_search,
    load_stopwords,
)

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
EMBEDDINGS_BIN = os.path.join("app", "src", "main", "assets", "embeddings.bin")
EMBEDDINGS_META = os.path.join("app", "src", "main", "assets", "embeddings_meta.json")
GOLDEN_PATH = os.path.join("eval", "golden_v3.draft.jsonl")
NORMALIZE_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")
FUSION_CONFIG_OUT = os.path.join("app", "src", "main", "assets", "fusion_config.json")

EMBED_DIM = 384
SEED = 7
K_VALUES = [10, 60]
WKW_VALUES = [0.0, 0.25, 0.5, 1.0]
N_FOLDS = 5
CANDIDATE_POOL = 20
MRR_K = 10


def load_embeddings():
    with open(EMBEDDINGS_META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    dim = meta["dim"]
    rows = meta["rows"]
    mat = np.fromfile(EMBEDDINGS_BIN, dtype=np.float32).reshape(rows, dim)
    return mat, meta


def load_golden():
    questions = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return [q for q in questions if q.get("in_scope", False)]


def load_out_of_scope():
    questions = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                q = json.loads(line)
                if not q.get("in_scope", False):
                    questions.append(q)
    return questions


def dense_search(query_vec, embeddings, chunk_meta, top_k=CANDIDATE_POOL):
    scores = embeddings @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    results = []
    for idx in top_idx:
        cid, name, page, text = chunk_meta[idx]
        results.append((cid, name, page, text, float(scores[idx])))
    return results


def keyword_search(cur, query, stopwords, variant_map, variant="v2", top_k=CANDIDATE_POOL):
    kw_query, _ = build_keyword_query(query, stopwords, set(), variant_map, variant=variant)
    if not kw_query:
        return []
    return fts_search(cur, kw_query, top_k=top_k)


def weighted_rrf(dense_results, kw_results, w_dense=1.0, w_kw=0.5, k=60, top_k=5):
    """Weighted RRF with page de-duplication."""
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
    kw_results = dedupe(kw_results)

    scores = {}
    dense_keys = [(r[0], r[1]) for r in dense_results]
    kw_keys = [(r[0], r[1]) for r in kw_results]
    for rank, key in enumerate(dense_keys):
        scores[key] = scores.get(key, 0.0) + w_dense / (k + rank + 1)
    for rank, key in enumerate(kw_keys):
        scores[key] = scores.get(key, 0.0) + w_kw / (k + rank + 1)
    text_lookup = {}
    for r in dense_results + kw_results:
        text_lookup[(r[0], r[1])] = r[2]
    sorted_keys = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    return [(key[0], key[1], text_lookup.get(key, ""), score) for key, score in sorted_keys]


def strict_hit_at_k(results, target_chunk_id, alt_chunk_ids, k):
    """STRICT: target or any alt is in top-k."""
    valid_ids = {target_chunk_id} | set(alt_chunk_ids)
    for rank, r in enumerate(results[:k], start=1):
        if r[0] in valid_ids:
            return rank
    return None


def target_only_hit_at_k(results, target_chunk_id, k):
    """TARGET-ONLY: target chunk only, no alt_chunk_ids."""
    for rank, r in enumerate(results[:k], start=1):
        if r[0] == target_chunk_id:
            return rank
    return None


def lenient_hit_at_k(results, target_chunk_id, alt_chunk_ids, chunk_index_by_id, k):
    """LENIENT: STRICT or adjacent chunk (id +/- 1 in same book and page)."""
    rank = strict_hit_at_k(results, target_chunk_id, alt_chunk_ids, k)
    if rank is not None:
        return rank
    target_row = chunk_index_by_id.get(target_chunk_id)
    if target_row is None:
        return None
    _, _, target_page, _ = target_row
    adjacent_ids = set()
    for delta in (-1, 1):
        adj_id = target_chunk_id + delta
        adj_row = chunk_index_by_id.get(adj_id)
        if adj_row is not None and adj_row[2] == target_page:
            adjacent_ids.add(adj_id)
    if not adjacent_ids:
        return None
    for rank, r in enumerate(results[:k], start=1):
        if r[0] in adjacent_ids:
            return rank
    return None


def recall_at_k(results_list, hit_func, k):
    """Hit rate at k over ALL questions (denominator = number of questions)."""
    n = len(results_list)
    if n == 0:
        return 0.0, 0
    hits = sum(1 for row in results_list if hit_func(row, k) is not None)
    return hits / n, n


def mrr_at_k(results_list, hit_func, k=MRR_K):
    """MRR@k = mean over ALL questions of 1/rank of first hit; 0 when no hit."""
    n = len(results_list)
    if n == 0:
        return 0.0
    total = 0.0
    for row in results_list:
        rank = hit_func(row, k)
        if rank is not None:
            total += 1.0 / rank
    return total / n


def snippet_centred(text, query, window=300):
    """~window chars centred on the sentence with most query-word overlap."""
    query_words = set(re.findall(r"\w+", query.lower()))
    sentences = re.split(r"(?<=[.!?])\s+", text)
    best_sent = ""
    best_score = -1
    for sent in sentences:
        sent_words = set(re.findall(r"\w+", sent.lower()))
        score = len(query_words & sent_words)
        if score > best_score:
            best_score = score
            best_sent = sent
    if not best_sent:
        return text[:window]
    idx = text.find(best_sent)
    if idx < 0:
        return best_sent[:window]
    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(best_sent) + window // 2)
    return text[start:end]


def content_stems(text, stopwords, variant_map):
    """Distinct content stems (stopwords removed) of a text."""
    norm = normalize_text(text, variant_map)
    tokens = re.findall(r"\w+", norm)
    return {t for t in tokens if t and t not in stopwords}


def fts_match_count(cur, term):
    """Number of FTS5 chunks matching a single quoted term."""
    if not term:
        return 0
    try:
        return cur.execute(
            "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
            ('"' + term + '"',),
        ).fetchone()[0]
    except Exception:
        return 0


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

    embeddings, meta = load_embeddings()
    bin_sha256 = hashlib.sha256(open(EMBEDDINGS_BIN, "rb").read()).hexdigest()
    chunk_sha256 = meta.get("chunk_texts_sha256", "unknown")
    print(f"embeddings.bin sha256: {bin_sha256}")
    print(f"chunk_texts_sha256 from meta: {chunk_sha256}")
    print(f"embeddings rows: {meta.get('rows', 'unknown')}, dim: {meta.get('dim', 'unknown')}")

    # sha256 check: database chunk-text hash vs embeddings_meta.json.
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT text FROM chunks ORDER BY id")
    db_all_texts = "".join(r[0] for r in cur.fetchall())
    db_sha256 = hashlib.sha256(db_all_texts.encode("utf-8")).hexdigest()
    sha_match = db_sha256 == chunk_sha256
    print(f"sha256 check: db chunk-text hash = {db_sha256}")
    print(f"sha256 check: meta chunk_texts_sha256 = {chunk_sha256}")
    print(f"sha256 check: MATCH = {sha_match}")

    questions = load_golden()
    out_of_scope = load_out_of_scope()
    print(f"In-scope questions: {len(questions)}")
    print(f"Out-of-scope questions: {len(out_of_scope)}")

    chunk_meta = cur.execute(
        "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id ORDER BY c.id"
    ).fetchall()
    chunk_index_by_id = {row[0]: row for row in chunk_meta}

    variant_map = load_variant_map(NORMALIZE_MAP_PATH) if os.path.exists(NORMALIZE_MAP_PATH) else {}
    stopwords = load_stopwords()

    # Embed all questions.
    query_texts = [q["q"] for q in questions]
    query_vecs = embed_texts(query_texts, kind="query")

    # Pre-compute results for all questions and methods.
    question_data = {}
    for qi, q in enumerate(questions):
        qid = q["id"]
        target_id = q["target_chunk_id"]
        alt_ids = q.get("alt_chunk_ids") or []
        q_vec = query_vecs[qi]

        dense_res = dense_search(q_vec, embeddings, chunk_meta, top_k=CANDIDATE_POOL)

        kw_by_variant = {}
        for variant in ["v1", "v2", "v3", "v4"]:
            kw_res = keyword_search(
                cur, q["q"], stopwords, variant_map, variant=variant, top_k=CANDIDATE_POOL
            )
            kw_by_variant[variant] = kw_res

        question_data[qid] = {
            "question": q,
            "target_id": target_id,
            "alt_ids": alt_ids,
            "dense": dense_res,
            "keyword": kw_by_variant,
        }

    # ---------- Table 1 ----------
    print("\n=== Table 1: Dense and Keyword Variants (STRICT and LENIENT) ===")
    t1_lines = [
        "| Method | Definition | Hit@1 | Hit@3 | Hit@5 | MRR@10 | Count |",
        "|---|---|---|---|---|---|---|",
    ]

    def eval_method(results_list, hit_func):
        r1, n = recall_at_k(results_list, hit_func, 1)
        r3, _ = recall_at_k(results_list, hit_func, 3)
        r5, _ = recall_at_k(results_list, hit_func, 5)
        mrr = mrr_at_k(results_list, hit_func, MRR_K)
        return r1, r3, r5, mrr, n

    def strict_hit(row, k):
        return strict_hit_at_k(row["results"], row["target_id"], row["alt_ids"], k)

    def lenient_hit(row, k):
        return lenient_hit_at_k(row["results"], row["target_id"], row["alt_ids"], chunk_index_by_id, k)

    def target_only_hit(row, k):
        return target_only_hit_at_k(row["results"], row["target_id"], k)

    # Dense, STRICT.
    dense_strict_rows = []
    dense_lenient_rows = []
    dense_to_rows = []
    for qid, data in question_data.items():
        target_id = data["target_id"]
        alt_ids = data["alt_ids"]
        dense_strict_rows.append({
            "results": data["dense"],
            "target_id": target_id,
            "alt_ids": alt_ids,
        })
        dense_lenient_rows.append({
            "results": data["dense"],
            "target_id": target_id,
            "alt_ids": alt_ids,
        })
        dense_to_rows.append({
            "results": data["dense"],
            "target_id": target_id,
            "alt_ids": alt_ids,
        })

    r1, r3, r5, mrr, n = eval_method(dense_strict_rows, strict_hit)
    t1_lines.append(f"| dense | STRICT | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} | {n} |")
    r1, r3, r5, mrr, n = eval_method(dense_lenient_rows, lenient_hit)
    t1_lines.append(f"| dense | LENIENT | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} | {n} |")

    # Keyword variants.
    for variant in ["v1", "v2", "v3", "v4"]:
        kw_strict_rows = []
        kw_lenient_rows = []
        kw_to_rows = []
        for qid, data in question_data.items():
            target_id = data["target_id"]
            alt_ids = data["alt_ids"]
            kw_strict_rows.append({
                "results": data["keyword"][variant],
                "target_id": target_id,
                "alt_ids": alt_ids,
            })
            kw_lenient_rows.append({
                "results": data["keyword"][variant],
                "target_id": target_id,
                "alt_ids": alt_ids,
            })
            kw_to_rows.append({
                "results": data["keyword"][variant],
                "target_id": target_id,
                "alt_ids": alt_ids,
            })

        r1, r3, r5, mrr, n = eval_method(kw_strict_rows, strict_hit)
        t1_lines.append(f"| keyword v{variant} | STRICT | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} | {n} |")
        r1, r3, r5, mrr, n = eval_method(kw_lenient_rows, lenient_hit)
        t1_lines.append(f"| keyword v{variant} | LENIENT | {r1:.3f} | {r3:.3f} | {r5:.3f} | {mrr:.3f} | {n} |")

    print("\n".join(t1_lines))

    # Note on STRICT vs LENIENT: they match on real data when no target's adjacent
    # chunk (id +/- 1, same book and page) is retrieved while the target itself is
    # missed. The adjacency rule is implemented in lenient_hit_at_k and exercised
    # by tests/test_stage36d.py::test_lenient_ge_strict_and_can_differ.
    def _hit_rate(rows, hit_func):
        hits = sum(1 for r in rows if hit_func(r["results"]) is not None)
        return hits / len(rows) if rows else 0.0

    _pairs = [
        ("dense", dense_strict_rows, dense_lenient_rows),
    ]
    for variant in ["v1", "v2", "v3", "v4"]:
        kw_s = [{"results": d["keyword"][variant], "hit": lambda r, tid=d["target_id"], aids=d["alt_ids"]: strict_hit_at_k(r, tid, aids, 5)} for d in question_data.values()]
        kw_l = [{"results": d["keyword"][variant], "hit": lambda r, tid=d["target_id"], aids=d["alt_ids"]: lenient_hit_at_k(r, tid, aids, chunk_index_by_id, 5)} for d in question_data.values()]
        _pairs.append((f"keyword v{variant}", kw_s, kw_l))
    for name, s_rows, l_rows in _pairs:
        sr = _hit_rate(s_rows, lambda r, k: r["hit"](r["results"], k))
        lr = _hit_rate(l_rows, lambda r, k: r["hit"](r["results"], k))
        flag = "identical (no adjacent chunk flips a miss on this data)" if sr == lr else "LENIENT > STRICT"
        print(f"STRICT vs LENIENT hit@5 for {name}: {sr:.3f} vs {lr:.3f} -> {flag}")

    # ---------- Table 2: 5-fold Cross-Validation ----------
    print("\n=== Table 2: 5-Fold Cross-Validation (STRICT metric) ===")
    rng = random.Random(SEED)
    indices = list(range(len(questions)))
    rng.shuffle(indices)
    fold_size = len(indices) // N_FOLDS
    folds = [indices[i * fold_size:(i + 1) * fold_size] for i in range(N_FOLDS)]
    # Distribute any leftover questions into the last fold.
    if len(indices) % N_FOLDS:
        folds[-1].extend(indices[N_FOLDS * fold_size:])

    cv_lines = [
        "| Config | Fold | Hit@1 | Hit@3 | Hit@5 | MRR@10 |",
        "|---|---|---|---|---|---|",
    ]
    config_fold_results = {}
    for k in K_VALUES:
        for wkw in WKW_VALUES:
            for fold_idx, fold_qids in enumerate(folds):
                n = len(fold_qids)
                hits1 = hits3 = hits5 = 0
                mrr_sum = 0.0
                for qid in fold_qids:
                    data = question_data[qid]
                    fused = weighted_rrf(
                        data["dense"], data["keyword"]["v2"],
                        w_dense=1.0, w_kw=wkw, k=k, top_k=MRR_K,
                    )
                    rank = strict_hit_at_k(
                        fused, data["target_id"], data["alt_ids"], MRR_K
                    )
                    if rank is not None:
                        if rank <= 1:
                            hits1 += 1
                        if rank <= 3:
                            hits3 += 1
                        if rank <= 5:
                            hits5 += 1
                        mrr_sum += 1.0 / rank
                mrr = mrr_sum / n if n else 0.0
                cv_lines.append(
                    f"| k={k}, w_kw={wkw} | {fold_idx + 1} | "
                    f"{hits1 / n:.3f} | {hits3 / n:.3f} | {hits5 / n:.3f} | {mrr:.3f} |"
                )
                config_fold_results.setdefault((k, wkw), []).append({
                    "fold": fold_idx + 1,
                    "hit1": hits1 / n, "hit3": hits3 / n, "hit5": hits5 / n, "mrr": mrr,
                })

    print("\n".join(cv_lines))

    # Mean +/- std.
    print(
        "| Config | Mean Hit@1 | Std Hit@1 | Mean Hit@3 | Std Hit@3 | Mean Hit@5 | Std Hit@5 | Mean MRR@10 | Std MRR@10 |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    config_means = {}
    for k in K_VALUES:
        for wkw in WKW_VALUES:
            folds_m = config_fold_results[(k, wkw)]
            means = {
                "hit1": np.mean([f["hit1"] for f in folds_m]),
                "hit3": np.mean([f["hit3"] for f in folds_m]),
                "hit5": np.mean([f["hit5"] for f in folds_m]),
                "mrr": np.mean([f["mrr"] for f in folds_m]),
            }
            stds = {
                "hit1": np.std([f["hit1"] for f in folds_m]),
                "hit3": np.std([f["hit3"] for f in folds_m]),
                "hit5": np.std([f["hit5"] for f in folds_m]),
                "mrr": np.std([f["mrr"] for f in folds_m]),
            }
            config_means[(k, wkw)] = (means, stds)
            print(
                f"| k={k}, w_kw={wkw} | {means['hit1']:.3f} | {stds['hit1']:.3f} | "
                f"{means['hit3']:.3f} | {stds['hit3']:.3f} | "
                f"{means['hit5']:.3f} | {stds['hit5']:.3f} | "
                f"{means['mrr']:.3f} | {stds['mrr']:.3f} |"
            )

    # Choose config.
    base_hit3 = config_means[(K_VALUES[0], 0.0)][0]["hit3"]
    print(f"\nBase hit@3 (w_kw=0): {base_hit3:.3f}")
    threshold = base_hit3 + 0.03
    chosen = None
    for wkw in sorted(WKW_VALUES):
        if wkw == 0.0:
            continue
        for k in sorted(K_VALUES):
            if config_means[(k, wkw)][0]["hit3"] >= threshold:
                chosen = (k, wkw)
                break
        if chosen:
            break

    if chosen is None:
        chosen = (K_VALUES[0], 0.0)
        print("No w_kw > 0 beats w_kw=0 by >= 0.03. Keeping w_kw=0.")
    else:
        print(f"Chosen config: k={chosen[0]}, w_kw={chosen[1]}")

    config = {
        "k": chosen[0],
        "w_dense": 1.0,
        "w_kw": chosen[1],
        "method": "weighted_rrf",
    }
    os.makedirs(os.path.dirname(FUSION_CONFIG_OUT), exist_ok=True)
    with open(FUSION_CONFIG_OUT, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {FUSION_CONFIG_OUT}: {config}")

    # ---------- Bias table: STRICT vs TARGET-ONLY by lexical-overlap group ----------
    print("\n=== Bias Table: STRICT vs TARGET-ONLY by Lexical Overlap Group ===")
    bias_lines = [
        "| Method | Definition | Overlap group | Count | Hit@1 | Hit@3 | Hit@5 | MRR@10 |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def overlap_group(overlap):
        if overlap <= 1:
            return "<= 1"
        if overlap <= 3:
            return "2-3"
        return ">= 4"

    # Build per-question items with overlap and precomputed results.
    items = []
    for qid, data in question_data.items():
        target_id = data["target_id"]
        alt_ids = data["alt_ids"]
        target_row = chunk_index_by_id.get(target_id)
        target_text = target_row[3] if target_row else ""
        overlap = len(
            content_stems(data["question"]["q"], stopwords, variant_map)
            & content_stems(target_text, stopwords, variant_map)
        )
        group = overlap_group(overlap)
        # Fused results at chosen config, top-10 (prefix gives top-5).
        fused_res = weighted_rrf(
            data["dense"], data["keyword"]["v2"],
            w_dense=1.0, w_kw=chosen[1], k=chosen[0], top_k=MRR_K,
        )
        items.append({
            "qid": qid,
            "overlap": overlap,
            "group": group,
            "target_id": target_id,
            "alt_ids": alt_ids,
            "dense_res": data["dense"],
            "fused_res": fused_res,
        })

    groups = ["<= 1", "2-3", ">= 4"]
    for method in ["dense", "fused"]:
        for definition in ["STRICT", "TARGET-ONLY"]:
            for group in groups:
                sub = [it for it in items if it["group"] == group]
                n = len(sub)
                if n == 0:
                    bias_lines.append(f"| {method} | {definition} | {group} | 0 | - | - | - | - |")
                    continue
                res = {}
                for k in [1, 3, 5]:
                    hits = 0
                    for it in sub:
                        tid = it["target_id"]
                        aids = it["alt_ids"] if definition == "STRICT" else []
                        results = it[method + "_res"]
                        if strict_hit_at_k(results, tid, aids, k) is not None:
                            hits += 1
                    res[k] = hits / n
                mrr_sum = 0.0
                for it in sub:
                    tid = it["target_id"]
                    aids = it["alt_ids"] if definition == "STRICT" else []
                    rank = strict_hit_at_k(it[method + "_res"], tid, aids, MRR_K)
                    if rank is not None:
                        mrr_sum += 1.0 / rank
                res["mrr"] = mrr_sum / n
                bias_lines.append(
                    f"| {method} | {definition} | {group} | {n} | "
                    f"{res[1]:.3f} | {res[3]:.3f} | {res[5]:.3f} | {res['mrr']:.3f} |"
                )

    print("\n".join(bias_lines))

    # ---------- Alternates audit ----------
    print("\n=== Alternates Audit ===")
    alt_lines = [
        "| Q id | Alt chunk id | Alt page | Source | Alt snippet (200 chars) |",
        "|---|---|---|---|---|",
    ]
    total_alternates = 0
    dense_source_count = 0
    keyword_source_count = 0
    for qid, data in question_data.items():
        target_id = data["target_id"]
        alt_ids = data.get("alt_ids") or []
        if not alt_ids:
            continue
        dense_ids = set(r[0] for r in data["dense"][:5])
        kw_ids = set(r[0] for r in data["keyword"]["v2"][:5])
        qtext = data["question"]["q"]
        for alt_id in alt_ids:
            total_alternates += 1
            alt_row = chunk_index_by_id.get(alt_id)
            if alt_row is None:
                alt_lines.append(f"| {qid} | {alt_id} | - | - | (chunk not in DB) |")
                continue
            alt_page = alt_row[2]
            alt_text = alt_row[3]
            snip = snippet_centred(alt_text, qtext, 200)
            source_parts = []
            if alt_id in dense_ids:
                source_parts.append("dense")
                dense_source_count += 1
            if alt_id in kw_ids:
                source_parts.append("keyword")
                keyword_source_count += 1
            source = "+".join(source_parts) if source_parts else "none"
            alt_lines.append(f"| {qid} | {alt_id} | {alt_page} | {source} | {snip} |")

    print("\n".join(alt_lines))
    print(f"Total alternates: {total_alternates}")
    print(f"Alternates from dense top-5: {dense_source_count}")
    print(f"Alternates from keyword top-5: {keyword_source_count}")

    # ---------- Golden v3 full listing with overlap ----------
    print("\n=== Golden v3 Full Listing (with overlap) ===")
    list_lines = [
        "| id | question | target chunk id | page | alt ids | overlap |",
        "|---|---|---|---|---|---|",
    ]
    for qid, data in question_data.items():
        target_id = data["target_id"]
        target_row = chunk_index_by_id.get(target_id)
        page = target_row[2] if target_row else "-"
        target_text = target_row[3] if target_row else ""
        overlap = len(
            content_stems(data["question"]["q"], stopwords, variant_map)
            & content_stems(target_text, stopwords, variant_map)
        )
        alt_str = ",".join(map(str, data.get("alt_ids") or [])) or "-"
        qtext = data["question"]["q"].replace("|", "\\|")
        list_lines.append(
            f"| {qid} | {qtext} | {target_id} | {page} | {alt_str} | {overlap} |"
        )
    print("\n".join(list_lines))

    # ---------- Out-of-scope rows ----------
    print("\n=== Out-of-Scope Rows (FTS match count per key term) ===")
    oos_lines = [
        "| id | question | key_terms | FTS match count per key term |",
        "|---|---|---|---|",
    ]
    for q in out_of_scope:
        qid = q["id"]
        qtext = q["q"].replace("|", "\\|")
        key_terms = q.get("key_terms") or []
        term_counts = []
        for term in key_terms:
            term_counts.append(f"{term}={fts_match_count(cur, term)}")
        oos_lines.append(
            f"| {qid} | {qtext} | {', '.join(key_terms) or '-'} | {'; '.join(term_counts) or '-'} |"
        )
    print("\n".join(oos_lines))

    # ---------- Failure review under chosen config ----------
    print("\n=== Failure Review (STRICT, top-5, chosen config) ===")
    k_chosen, wkw_chosen = chosen
    failures = []
    for qid, data in question_data.items():
        target_id = data["target_id"]
        alt_ids = data["alt_ids"]
        dense_res = data["dense"]
        kw_res = data["keyword"]["v2"]
        fused = weighted_rrf(
            dense_res, kw_res, w_dense=1.0, w_kw=wkw_chosen, k=k_chosen, top_k=5
        )
        rank = strict_hit_at_k(fused, target_id, alt_ids, 5)

        if rank is not None:
            continue

        target_row = chunk_index_by_id.get(target_id)
        target_text = target_row[3] if target_row else "UNKNOWN"
        top3 = []
        for r in fused[:3]:
            r_text = chunk_index_by_id.get(r[0], (None, None, None, ""))[3] or ""
            top3.append((r[0], r[1], snippet_centred(r_text, data["question"]["q"], 300)))
        failures.append({
            "id": qid,
            "question": data["question"]["q"],
            "target_id": target_id,
            "target_text": target_text,
            "top3": top3,
        })

    print(f"Failures (no STRICT hit in top-5): {len(failures)} of {len(questions)}")
    for f in failures:
        print(f"\n--- Q{f['id']}: {f['question']} ---")
        print(f"Target chunk {f['target_id']} (first 300 chars): {f['target_text'][:300]}")
        print("Top-3 retrieved:")
        for cid, page, snippet in f["top3"]:
            print(f"  Chunk {cid} (page {page}): {snippet[:300]}")

    # Step summary.
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n## Golden v3 Re-measurement\n\n")
            f.write(f"In-scope questions: {len(questions)}\n")
            f.write(f"Out-of-scope questions: {len(out_of_scope)}\n")
            f.write(f"Chosen fusion config: k={chosen[0]}, w_kw={chosen[1]}\n")
            f.write(f"Base hit@3 (w_kw=0): {base_hit3:.3f}\n")
            f.write(f"sha256 check MATCH: {sha_match}\n\n")
            f.write("### Table 1\n\n")
            f.write("\n".join(t1_lines) + "\n\n")
            f.write("### Table 2\n\n")
            f.write("\n".join(cv_lines) + "\n\n")
            f.write("### Bias Table\n\n")
            f.write("\n".join(bias_lines) + "\n\n")
            f.write("### Alternates Audit\n\n")
            f.write("\n".join(alt_lines) + "\n")
            f.write(f"Total alternates: {total_alternates}\n")
            f.write(f"Alternates from dense top-5: {dense_source_count}\n")
            f.write(f"Alternates from keyword top-5: {keyword_source_count}\n\n")
            f.write("### Golden v3 Listing\n\n")
            f.write("\n".join(list_lines) + "\n\n")
            f.write("### Out-of-Scope Rows\n\n")
            f.write("\n".join(oos_lines) + "\n\n")
            f.write("### Failures\n\n")
            f.write(f"Failures: {len(failures)} of {len(questions)}\n")

    conn.close()
    print("\nGolden v3 re-measurement complete.")


if __name__ == "__main__":
    main()
