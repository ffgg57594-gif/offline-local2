#!/usr/bin/env python3
"""Phase 1: Ingestion - extract text per page, split into chapters > paragraphs > sentences.
Store in SQLite (books, chapters, paragraphs, sentences) with page numbers.
Usage: python3 scripts/ingest.py <pdf_path> <book_title> [out_db]
"""
import sys, os, re, sqlite3

def get_pages(pdf_path):
    from pypdf import PdfReader
    r = PdfReader(pdf_path)
    pages = []
    for i, p in enumerate(r.pages):
        txt = p.extract_text() or ""
        pages.append((i+1, txt))
    return pages, len(r.pages)

HEADING_PATTERNS = [
    re.compile(r"^\d+\.\d+\s+\S"),          # 27.1 Congenital...
    re.compile(r"^[IVX]+\.\s+\S"),          # Roman numeral sections
    re.compile(r"^[A-Z][A-Z \-]{3,60}$"),   # ALL CAPS headings
    re.compile(r"^(Chapter|CHAPTER)\s+\d+"),
    re.compile(r"^(Introduction|Mood Disorders|Anxiety|Schizophrenia|Somatic|Substance|Child|Neurocognitive|Emergency|Psychotherapeutic)\b"),
]

def is_heading(line):
    line = line.strip()
    if not line or len(line) > 80:
        return False
    for pat in HEADING_PATTERNS:
        if pat.match(line):
            return True
    return False

def split_sentences(text):
    # simple sentence splitter
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]

def chunk_paragraphs(paras_raw, target_min=150, target_max=250):
    """Group sentences into paragraphs of 150-250 words."""
    out = []
    for raw in paras_raw:
        words = raw.split()
        if len(words) <= target_max:
            out.append(raw.strip())
            continue
        # split into sentence groups
        sents = split_sentences(raw)
        buf = []
        bufw = 0
        for s in sents:
            sw = len(s.split())
            if buf and bufw + sw > target_max:
                out.append(" ".join(buf).strip())
                buf = [s]; bufw = sw
            else:
                buf.append(s); bufw += sw
            if bufw >= target_min and bufw <= target_max:
                # flush when in range if next would exceed
                pass
        if buf:
            out.append(" ".join(buf).strip())
    # merge tiny trailing chunks into previous
    merged = []
    for p in out:
        if merged and len(p.split()) < 80:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    return [p for p in merged if p.strip()]

def main():
    if len(sys.argv) < 3:
        print("usage: ingest.py <pdf> <title> [db]")
        sys.exit(1)
    pdf_path = sys.argv[1]
    title = sys.argv[2]
    db_path = sys.argv[3] if len(sys.argv) > 3 else "ingested.db"
    pages, numpages = get_pages(pdf_path)
    print(f"Pages: {numpages}")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS books (id INTEGER PRIMARY KEY, title TEXT, path TEXT, pages INTEGER);
    CREATE TABLE IF NOT EXISTS chapters (id INTEGER PRIMARY KEY, book_id INTEGER, title TEXT, FOREIGN KEY(book_id) REFERENCES books(id));
    CREATE TABLE IF NOT EXISTS paragraphs (id INTEGER PRIMARY KEY, book_id INTEGER, chapter_id INTEGER, page INTEGER, text TEXT, word_count INTEGER, FOREIGN KEY(book_id) REFERENCES books(id), FOREIGN KEY(chapter_id) REFERENCES chapters(id));
    CREATE TABLE IF NOT EXISTS sentences (id INTEGER PRIMARY KEY, paragraph_id INTEGER, book_id INTEGER, chapter_id INTEGER, page INTEGER, text TEXT, with_chapter TEXT, FOREIGN KEY(paragraph_id) REFERENCES paragraphs(id));
    """)
    # clear existing data for this book title
    c.execute("DELETE FROM sentences WHERE book_id IN (SELECT id FROM books WHERE title=?)", (title,))
    c.execute("DELETE FROM paragraphs WHERE book_id IN (SELECT id FROM books WHERE title=?)", (title,))
    c.execute("DELETE FROM chapters WHERE book_id IN (SELECT id FROM books WHERE title=?)", (title,))
    c.execute("DELETE FROM books WHERE title=?", (title,))
    c.execute("INSERT INTO books(title,path,pages) VALUES(?,?,?)", (title, pdf_path, numpages))
    book_id = c.lastrowid

    chapter_map = {}  # title -> id
    def get_chapter(ch_title):
        if ch_title not in chapter_map:
            c.execute("INSERT INTO chapters(book_id,title) VALUES(?,?)", (book_id, ch_title))
            chapter_map[ch_title] = c.lastrowid
        return chapter_map[ch_title]

    current_chapter = "Introduction"
    get_chapter(current_chapter)

    total_paras = 0
    total_sents = 0
    for pageno, text in pages:
        lines = text.splitlines()
        # detect chapter headings in this page
        for ln in lines:
            if is_heading(ln):
                current_chapter = ln.strip()
                get_chapter(current_chapter)
        # split into paragraphs by blank lines
        raw_paras = re.split(r"\n\s*\n", text)
        raw_paras = [p.replace("\n", " ") for p in raw_paras]
        raw_paras = [re.sub(r"\s+", " ", p).strip() for p in raw_paras if p.strip()]
        # filter out very short (page numbers, headers)
        raw_paras = [p for p in raw_paras if len(p.split()) >= 20]
        paras = chunk_paragraphs(raw_paras)
        for para in paras:
            wc = len(para.split())
            ch_id = get_chapter(current_chapter)
            c.execute("INSERT INTO paragraphs(book_id,chapter_id,page,text,word_count) VALUES(?,?,?,?,?)",
                      (book_id, ch_id, pageno, para, wc))
            pid = c.lastrowid
            total_paras += 1
            for s in split_sentences(para):
                with_ch = f"[{current_chapter}] {s}"
                c.execute("INSERT INTO sentences(paragraph_id,book_id,chapter_id,page,text,with_chapter) VALUES(?,?,?,?,?,?)",
                          (pid, book_id, ch_id, pageno, s, with_ch))
                total_sents += 1
    conn.commit()
    # stats
    c.execute("SELECT COUNT(*) FROM paragraphs WHERE book_id=?", (book_id,))
    np_ = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sentences WHERE book_id=?", (book_id,))
    ns_ = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM chapters WHERE book_id=?", (book_id,))
    nc_ = c.fetchone()[0]
    print(f"Book: {title}")
    print(f"Pages: {numpages}")
    print(f"Chapters detected: {nc_}")
    print(f"Paragraphs: {np_}")
    print(f"Sentences: {ns_}")
    print(f"Avg words/para: {sum(len(p.split()) for p in []) or 0}")
    conn.close()

if __name__ == "__main__":
    main()
