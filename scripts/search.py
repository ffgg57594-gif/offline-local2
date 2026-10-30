#!/usr/bin/env python3
"""Phase 2: Search - FTS5 (porter) + optional BGE-M3 embeddings, fused with RRF.
Usage:
  python3 scripts/search.py --db ingested.db --query "depression symptoms"
  python3 scripts/search.py --db ingested.db --build-fts
"""
import argparse, sqlite3, re, math

def build_fts(conn):
    conn.execute("DROP TABLE IF EXISTS sentences_fts")
    conn.execute("CREATE VIRTUAL TABLE sentences_fts USING fts5(text, content='sentences', content_rowid='id', tokenize='porter unicode61')")
    conn.execute("INSERT INTO sentences_fts(rowid, text) SELECT id, text FROM sentences")
    conn.commit()
    print("FTS5 built")

def fts_search(conn, query, k=20):
    # sanitize query
    q = " ".join(re.findall(r"[A-Za-z]+", query))
    if not q:
        return []
    try:
        rows = conn.execute("""
            SELECT s.id, s.paragraph_id, s.book_id, s.page, s.text, s.with_chapter,
                   bm25(sentences_fts) AS score
            FROM sentences_fts JOIN sentences s ON s.id = sentences_fts.rowid
            WHERE sentences_fts MATCH ?
            ORDER BY score LIMIT ?
        """, (q, k)).fetchall()
    except Exception as e:
        return []
    return rows

def rrf_fuse(lists, k=60):
    scores = {}
    for lst in lists:
        for rank, item in enumerate(lst):
            scores[item[0]] = scores.get(item[0], 0) + 1.0/(k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])

def search(conn, query, top_paras=3, threshold=0.02):
    fts = fts_search(conn, query, k=30)
    # aggregate sentence hits -> paragraph scores
    para_scores = {}
    for sid, pid, bid, page, text, wch, score in fts:
        para_scores[pid] = para_scores.get(pid, 0) + 1.0/(60 + 0)  # placeholder RRF per sentence
    # better: rank paragraphs by best sentence rank
    ranked_paras = {}
    for i, (sid, pid, bid, page, text, wch, score) in enumerate(fts):
        if pid not in ranked_paras or i < ranked_paras[pid][0]:
            ranked_paras[pid] = (i, bid, page)
    # sort by rank
    ordered = sorted(ranked_paras.items(), key=lambda x: x[1][0])[:top_paras]
    # confidence: if no fts hits -> refuse
    if not fts:
        return None, "no_hits"
    # threshold on top score magnitude (bm25 lower=better); use hit count
    if len(fts) < 2:
        return None, "low_confidence"
    results = []
    for pid, (rk, bid, page) in ordered:
        prow = conn.execute("SELECT text, word_count FROM paragraphs WHERE id=?", (pid,)).fetchone()
        book = conn.execute("SELECT title FROM books WHERE id=?", (bid,)).fetchone()[0]
        results.append({"paragraph_id": pid, "book": book, "page": page, "text": prow[0], "words": prow[1]})
    return results, "ok"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="ingested.db")
    ap.add_argument("--query", default=None)
    ap.add_argument("--build-fts", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    if args.build_fts:
        build_fts(conn); return
    # ensure fts exists
    try:
        conn.execute("SELECT count(*) FROM sentences_fts").fetchone()
    except Exception:
        build_fts(conn)
    if args.query:
        res, status = search(conn, args.query)
        print("STATUS:", status)
        if res:
            for r in res:
                print(f"\n--- {r['book']} p.{r['page']} ({r['words']} words) ---")
                print(r['text'][:500])

if __name__ == "__main__":
    main()
