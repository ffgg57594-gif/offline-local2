# Phase 2 full search: FTS5 + BGE-M3 + RRF. Run on Colab (free) or Termux.
# !pip install sentence-transformers faiss-cpu (Colab)
import sqlite3, re, json, os
import numpy as np
from sentence_transformers import SentenceTransformer

DB = "ingested.db"
MODEL = "BAAI/bge-m3"

def build_fts(conn):
    conn.execute("DROP TABLE IF EXISTS sentences_fts")
    conn.execute("CREATE VIRTUAL TABLE sentences_fts USING fts5(text, content='sentences', content_rowid='id', tokenize='porter unicode61')")
    conn.execute("INSERT INTO sentences_fts(rowid, text) SELECT id, text FROM sentences")
    conn.commit()

def embed_sentences(conn, model):
    rows = conn.execute("SELECT id, text FROM sentences").fetchall()
    ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]
    embs = model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=True)
    np.save("sent_emb_ids.npy", np.array(ids))
    np.save("sent_emb.npy", embs)
    return ids, embs

def search(conn, model, query, top_paras=3):
    # FTS
    toks = " ".join(re.findall(r"[A-Za-z]+", query))
    fts_ids = []
    if toks:
        try:
            fts_ids = [r[0] for r in conn.execute(
                "SELECT s.id FROM sentences_fts JOIN sentences s ON s.id=sentences_fts.rowid WHERE sentences_fts MATCH ? LIMIT 30",(toks,)).fetchall()]
        except Exception:
            pass
    # Embedding
    qemb = model.encode([query], normalize_embeddings=True)[0]
    ids = np.load("sent_emb_ids.npy")
    embs = np.load("sent_emb.npy")
    sims = embs @ qemb
    top_idx = np.argsort(-sims)[:30]
    emb_ids = [int(ids[i]) for i in top_idx]
    # RRF fuse
    def rrf(lists, k=60):
        sc={}
        for lst in lists:
            for rank,x in enumerate(lst):
                sc[x]=sc.get(x,0)+1.0/(k+rank+1)
        return sorted(sc.items(), key=lambda z:-z[1])
    fused = rrf([fts_ids, emb_ids])
    # aggregate to paragraphs
    para_best={}
    for sid,score in fused:
        pid = conn.execute("SELECT paragraph_id,book_id,page FROM sentences WHERE id=?",(sid,)).fetchone()
        if not pid: continue
        para_best.setdefault(pid[0], (score, pid[1], pid[2]))
    ordered = sorted(para_best.items(), key=lambda z:-z[1][0])[:top_paras]
    # confidence threshold
    top_score = ordered[0][1][0] if ordered else 0
    if top_score < 0.015:
        return None, "low_confidence"
    if not fused:
        return None, "no_hits"
    results=[]
    for pid,(sc,bid,page) in ordered:
        text = conn.execute("SELECT text,word_count FROM paragraphs WHERE id=?",(pid,)).fetchone()
        book = conn.execute("SELECT title FROM books WHERE id=?",(bid,)).fetchone()[0]
        results.append({"paragraph_id":pid,"book":book,"page":page,"text":text[0],"words":text[1],"score":float(sc)})
    return results, "ok"

if __name__=="__main__":
    conn = sqlite3.connect(DB)
    build_fts(conn)
    model = SentenceTransformer(MODEL)
    embed_sentences(conn, model)
    # quick test
    for q in ["depression symptoms","breast abscess treatment","goitre classification"]:
        r,st = search(conn, model, q)
        print(q, "->", st, (r[0]["book"]+" p."+str(r[0]["page"])) if r else None)
