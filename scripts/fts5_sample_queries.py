#!/usr/bin/env python3
"""Run 5 sample FTS5 queries against the built books_knowledge.db and print
the book/page of the top result for each."""
import os
import re
import sqlite3
import sys
from collections import Counter

DB = os.path.join("app", "src", "main", "assets", "books_knowledge.db")

if not os.path.exists(DB):
    print(f"ERROR: {DB} not found", file=sys.stderr)
    sys.exit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

rows = cur.execute(
    "SELECT c.id, b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id"
).fetchall()

stop = {
    "the","and","of","a","to","in","is","it","that","with","for","on","as","by",
    "are","was","be","this","have","had","has","not","but","from","or","an","at",
    "which","you","your","we","they","their","our","he","she","his","her","its",
    "been","were","will","would","could","should","may","can","into","than",
}
cnt = Counter()
for _cid, _name, _page, text in rows:
    for w in re.findall(r"[A-Za-z\u0600-\u06FF]+", text.lower()):
        if len(w) > 3 and w not in stop:
            cnt[w] += 1

queries = [w for w, _ in cnt.most_common(5)]
if not queries:
    print("No queryable words found in DB.")
    sys.exit(0)

print("| Query | Top book | Top page | Snippet |")
print("|---|---|---|---|")
for q in queries:
    cur.execute(
        "SELECT b.name, c.page, c.text "
        "FROM chunks_fts f "
        "JOIN chunks c ON c.id = f.rowid "
        "JOIN books b ON b.id = c.book_id "
        "WHERE f.text MATCH ? "
        "ORDER BY c.id LIMIT 1",
        (q,),
    )
    row = cur.fetchone()
    if row:
        snippet = row[2].replace("\n", " ")[:90].replace("|", "\\|")
        print(f"| {q} | {row[0]} | {row[1]} | {snippet} |")
    else:
        print(f"| {q} | - | - | no result |")

step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
if step_summary:
    with open(step_summary, "a", encoding="utf-8") as f:
        f.write("## Sample FTS5 queries\n\n")
        f.write("| Query | Top book | Top page | Snippet |\n")
        f.write("|---|---|---|---|\n")
        for q in queries:
            cur.execute(
                "SELECT b.name, c.page, c.text "
                "FROM chunks_fts f "
                "JOIN chunks c ON c.id = f.rowid "
                "JOIN books b ON b.id = c.book_id "
                "WHERE f.text MATCH ? "
                "ORDER BY c.id LIMIT 1",
                (q,),
            )
            row = cur.fetchone()
            if row:
                snippet = row[2].replace("\n", " ")[:90].replace("|", "\\|")
                f.write(f"| {q} | {row[0]} | {row[1]} | {snippet} |\n")
            else:
                f.write(f"| {q} | - | - | no result |\n")
        f.write("\n")
conn.close()
