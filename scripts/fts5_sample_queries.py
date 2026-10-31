#!/usr/bin/env python3
"""Run 8 sample FTS5 queries against the built books_knowledge.db and print
the top 3 results (ordered by BM25 rank) with book, page, and a 120-char snippet.
The step FAILS if any top-3 result comes from a skipped page.
"""
import os
import re
import sqlite3
import sys
import unicodedata

DB = os.path.join("app", "src", "main", "assets", "books_knowledge.db")

QUERIES = [
    "fetal",
    "pregnancy",
    "vaginal",
    "uterine",
    "postpartum hemorrhage",
    "causes of preterm labour",
    "gestational diabetes",
    "pre-eclampsia",
]

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def is_arabic(text):
    return bool(ARABIC_RE.search(text))


def normalize_arabic(text):
    """Strip Arabic diacritics and tatweel for safe matching."""
    text = unicodedata.normalize("NFKC", text)
    # Remove Arabic diacritics (Mn category) and tatweel (U+0640).
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn" and ch != "\u0640")


def build_fts_query(query):
    """Safe FTS5 query: quote each token, join multi-word tokens with OR."""
    if is_arabic(query):
        query = normalize_arabic(query)
    tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    quoted = [f'"{t}"' for t in tokens]
    if len(quoted) == 1:
        return quoted[0]
    return " OR ".join(quoted)


def main():
    if not os.path.exists(DB):
        print(f"ERROR: {DB} not found", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA table_info(chunks_fts)")  # ensure FTS5 exists
    cur = conn.cursor()

    # Load skipped pages from meta so we can fail if a top-3 result is skipped.
    skipped_meta = {}
    for row in cur.execute("SELECT key, value FROM meta WHERE key LIKE 'skip_reason_p%_%'"):
        key, value = row
        # key format: skip_reason_p<book_id>_<page>
        m = re.match(r"skip_reason_p(\d+)_(\d+)$", key)
        if m:
            book_id = int(m.group(1))
            page = int(m.group(2))
            skipped_meta.setdefault(book_id, set()).add(page)

    book_id_to_name = {bid: name for bid, name in cur.execute("SELECT id, name FROM books")}

    output_lines = ["| Query | Rank | Book | Page | Snippet |", "|---|---|---|---|---|"]
    summary_lines = ["## Sample FTS5 queries (top 3, BM25)", "",
                     "| Query | Rank | Book | Page | Snippet |", "|---|---|---|---|---|"]

    failed = False
    for q in QUERIES:
        fts_q = build_fts_query(q)
        try:
            cur.execute(
                "SELECT b.name, c.page, c.text, bm25(chunks_fts) AS rank "
                "FROM chunks_fts f "
                "JOIN chunks c ON c.id = f.rowid "
                "JOIN books b ON b.id = c.book_id "
                "WHERE f.text MATCH ? "
                "ORDER BY rank LIMIT 3",
                (fts_q,),
            )
        except sqlite3.OperationalError as e:
            print(f"FTS5 query error for '{q}': {e}", file=sys.stderr)
            sys.exit(1)

        rows = cur.fetchall()
        if not rows:
            output_lines.append(f"| {q} | - | - | - | no result |")
            summary_lines.append(f"| {q} | - | - | - | no result |")
            continue

        for rank, (name, page, text, _r) in enumerate(rows, start=1):
            bid = next((b for b, n in book_id_to_name.items() if n == name), None)
            is_skipped = bid is not None and page in skipped_meta.get(bid, set())
            if is_skipped:
                failed = True
            snippet = re.sub(r"\s+", " ", text).strip()[:120].replace("|", "\\|")
            output_lines.append(f"| {q} | {rank} | {name} | {page} | {snippet} |")
            summary_lines.append(f"| {q} | {rank} | {name} | {page} | {snippet} |")

    output_lines.append("")
    summary_lines.append("")

    # --- Human check: 3 random chunks IN FULL (fixed seed 7) ---
    import random
    rng = random.Random(7)
    all_chunks = cur.execute(
        "SELECT b.name, c.page, c.text FROM chunks c JOIN books b ON b.id = c.book_id"
    ).fetchall()
    human_lines = ["## Human check: 3 random chunks (full text, seed 7)", ""]
    summary_lines.extend(human_lines)
    if all_chunks:
        sample = rng.sample(all_chunks, min(3, len(all_chunks)))
        long_word_chunks = 0
        for name, page, text in all_chunks:
            if any(len(w) > 25 for w in text.split()):
                long_word_chunks += 1
        pct_long = (long_word_chunks / len(all_chunks) * 100) if all_chunks else 0.0
        if pct_long > 5.0:
            warning = f"WARNING: {pct_long:.1f}% of chunks contain words longer than 25 characters (possible merged text/garbage)."
            print(warning, file=sys.stderr)
            human_lines.append(f"**Warning:** {warning}")
            human_lines.append("")
        for name, page, text in sample:
            human_lines.append(f"**Book:** {name}  |  **Page:** {page}")
            human_lines.append("")
            human_lines.append(text)
            human_lines.append("")
            human_lines.append("---")
            human_lines.append("")
        summary_lines.extend(human_lines)
    else:
        human_lines.append("*No chunks found.*")
        human_lines.append("")
        summary_lines.extend(human_lines)

    print("\n".join(output_lines))

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")

    conn.close()
    if failed:
        print("ERROR: A top-3 FTS5 result came from a skipped page.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
