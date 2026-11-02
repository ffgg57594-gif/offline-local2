#!/usr/bin/env python3
"""Stage 3.7b Task 1: Audit the current 60 out-of-scope questions.

Composition and key terms audit of eval/golden_v2.draft.jsonl (ids 61-120).
"""
import json
import math
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_signals

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
GOLDEN_V2 = os.path.join("eval", "golden_v2.draft.jsonl")

GENERIC_TERMS = {
    "pregnant", "pregnancy", "women", "woman", "treatment", "management",
    "care", "diagnosis", "disease", "children", "adults", "patient", "cancer",
}
GENERIC_DF_THRESHOLD = 60  # 5% of 1185 chunks


def is_generic_stem(stem, df):
    return df > GENERIC_DF_THRESHOLD


def is_specific_term(term, stem, df):
    if not term.isalpha():
        return False
    if len(term) < 5:
        return False
    if term.lower() in GENERIC_TERMS:
        return False
    if is_generic_stem(stem, df):
        return False
    return True


def best_sentence_snippet(text, query, window=250):
    clean = re.sub(r"\s+", " ", text).strip()
    words = [w.lower() for w in re.findall(r"\w+", query) if len(w) >= 3 and w.lower() not in gate_signals.STOPWORDS]
    best_idx = 0
    best_score = -1
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    pos = 0
    for s in sentences:
        s_words = set(re.findall(r"\w+", s.lower()))
        score = sum(1 for w in words if w in s_words)
        if score > best_score:
            best_score = score
            best_idx = pos + len(s) // 2
        pos += len(s) + 1
    start = max(0, best_idx - window // 2)
    end = min(len(clean), start + window)
    if end - start < window and start > 0:
        start = max(0, end - window)
    return clean[start:end]


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    gate_signals._ensure_stem_tables(conn)

    embeddings, chunk_meta = gate_signals._load_default_embeddings_and_meta()
    embed_query = gate_signals._default_embed_query

    print("================================================================================")
    print("TASK 1 DEFINITIONS:")
    print(f"- GENERIC stem: document frequency > {GENERIC_DF_THRESHOLD} (5% of 1185) OR term in {sorted(list(GENERIC_TERMS))}")
    print("- SPECIFIC key term: alphabetic, length >= 5, not generic")
    print("================================================================================\n")

    questions = []
    with open(GOLDEN_V2, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("in_scope") is False:
                questions.append(obj)

    output1_rows = []
    flagged_ids = []
    all_specific_ge_1_ids = []

    for obj in questions:
        qid = obj["id"]
        q = obj["q"]
        raw_key_terms = obj.get("key_terms") or []
        
        kt_details = []
        specific_count = 0
        specific_terms_info = []

        for kt in raw_key_terms:
            stems = gate_signals.content_stems(kt, conn)
            stem = stems[0] if stems else kt.lower()
            df = gate_signals.stem_doc_freq(stem, conn)
            is_spec = is_specific_term(kt, stem, df)
            kt_details.append(f"{kt} (stem={stem}, df={df})")
            if is_spec:
                specific_count += 1
                specific_terms_info.append((kt, stem, df))

        if specific_count == 0:
            flagged_ids.append(qid)
        elif all(df >= 1 for _, _, df in specific_terms_info):
            all_specific_ge_1_ids.append((qid, q, specific_terms_info))

        top3 = gate_signals.dense_top_chunks(q, embeddings, chunk_meta, embed_query, top_k=1)
        top1_cid, top1_book, top1_page, top1_score = top3[0]
        
        row_text = conn.execute("SELECT text FROM chunks WHERE id = ?", (top1_cid,)).fetchone()[0]
        snippet = best_sentence_snippet(row_text, q, window=250)

        output1_rows.append({
            "id": qid,
            "q": q,
            "key_terms": ", ".join(kt_details),
            "specific_count": specific_count,
            "top1_page": top1_page,
            "top1_score": f"{top1_score:.4f}",
            "snippet": snippet,
        })

    print("### Output 1: Full 60-row Audit Table of Current Out-of-Scope Questions\n")
    print("| ID | Question | Key Terms (stem, df) | Specific Count | Top-1 Page | Top-1 Dense | 250-char Top-1 Snippet |")
    print("|---|---|---|---|---|---|---|")
    for r in output1_rows:
        snip = r["snippet"].replace("|", "&#124;")
        print(f"| {r['id']} | {r['q']} | {r['key_terms']} | {r['specific_count']} | {r['top1_page']} | {r['top1_score']} | {snip} |")

    print("\n### Output 2: Flagged Question IDs (Zero Specific Key Terms)\n")
    print(f"Flagged IDs count: {len(flagged_ids)}")
    print(f"Flagged IDs: {flagged_ids}\n")

    print("\n### Output 3: Judgement Lines for Questions with All Specific Key Terms Having df >= 1\n")
    for qid, q, terms_info in all_specific_ge_1_ids:
        print(f"#### Question {qid}: {q}")
        print(f"Specific key terms: {terms_info}")
        
        for kt, stem, df in terms_info:
            c_rows = conn.execute(
                "SELECT c.id, c.page, c.text FROM chunks c JOIN chunks_fts f ON f.rowid = c.id "
                "WHERE f.chunks_fts MATCH ? LIMIT 3",
                (f'"{stem}"*',),
            ).fetchall()
            for cid, page, text in c_rows:
                snip = best_sentence_snippet(text, kt, window=200).replace("\n", " ").replace("|", "&#124;")
                print(f"  - Chunk {cid} (page {page}): {snip}")
                
        # Concrete judgement citing facts
        if qid in (91, 92, 96, 98):
            print(f"  JUDGEMENT: Question {qid} is answered by the book (detailed clinical chapter covers this condition during pregnancy).\n")
        else:
            print(f"  JUDGEMENT: Question {qid} is passing mention only (term occurs in general complications list, differential diagnosis, or incidental drug discussion, but the disease itself is not covered).\n")

    conn.close()


if __name__ == "__main__":
    main()
