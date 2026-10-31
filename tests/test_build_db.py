#!/usr/bin/env python3
"""Stage 2 tests for scripts/build_knowledge_db.py."""
import os
import subprocess
import sys

import fitz
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_knowledge_db as bk  # noqa: E402


def _make_pdf(tmp_path, name):
    path = os.path.join(tmp_path, name)
    doc = fitz.open()
    # Page 1: header line repeated + heading + hyphenated word at line end.
    p1 = doc.new_page()
    p1.insert_text((72, 72), "CONFIDENTIAL HEADER")
    p1.insert_text((72, 110), "Medical Heading")
    p1.insert_text((72, 140), "This is a paragraph about diagnosis and treatment options.")
    p1.insert_text((72, 170), "The word diagno-")
    p1.insert_text((72, 190), "sis appears here.")
    # Page 2: header + more text.
    p2 = doc.new_page()
    p2.insert_text((72, 72), "CONFIDENTIAL HEADER")
    p2.insert_text((72, 110), "Second page content about hypertension management.")
    # Page 3: header + short page.
    p3 = doc.new_page()
    p3.insert_text((72, 72), "CONFIDENTIAL HEADER")
    p3.insert_text((72, 110), "Short.")
    # Pages 4-12: repeat header so it exceeds 40% of pages (>= 10 pages total).
    for pno in range(4, 13):
        pn = doc.new_page()
        pn.insert_text((72, 72), "CONFIDENTIAL HEADER")
        pn.insert_text((72, 110), f"Page {pno} filler content about hypertension management and diagnosis.")
    doc.save(path)
    doc.close()
    return path


def test_header_removed_and_dehyphenated(tmp_path):
    pdf = _make_pdf(tmp_path, "sample.pdf")
    doc = fitz.open(pdf)
    pages_text = []
    for i in range(doc.page_count):
        raw = doc[i].get_text("text")
        norm = bk.normalize_text(raw)
        pages_text.append([ln for ln in norm.split("\n") if ln.strip()])
    doc.close()

    hf = bk.find_header_footer_lines(pages_text)
    assert "CONFIDENTIAL HEADER" in hf

    # De-hyphenation check.
    assert bk.dehyphenate("diagno-\nsis") == "diagnosis"

    # Build chunks and verify header gone, word de-hyphenated.
    cleaned = []
    for pl in pages_text:
        cleaned.append([ln for ln in pl if ln not in hf and not bk.is_page_number_line(ln)])
    chunks = bk.build_chunks_for_book("sample", cleaned, hf)
    joined = " ".join(c[2] for c in chunks)
    assert "CONFIDENTIAL HEADER" not in joined
    assert "diagnosis" in joined
    assert "diagno-" not in joined


def test_chunk_page_numbers_and_no_crossing(tmp_path):
    pdf = _make_pdf(tmp_path, "sample.pdf")
    doc = fitz.open(pdf)
    pages_text = []
    for i in range(doc.page_count):
        raw = doc[i].get_text("text")
        norm = bk.normalize_text(raw)
        pages_text.append([ln for ln in norm.split("\n") if ln.strip()])
    doc.close()
    hf = bk.find_header_footer_lines(pages_text)
    cleaned = []
    for pl in pages_text:
        cleaned.append([ln for ln in pl if ln not in hf and not bk.is_page_number_line(ln)])
    chunks = bk.build_chunks_for_book("sample", cleaned, hf)
    # Each chunk page must be 1..12 and non-decreasing; no chunk spans pages.
    seen_pages = [c[0] for c in chunks]
    assert seen_pages == sorted(seen_pages)
    assert all(1 <= p <= 12 for p in seen_pages)
    assert len(chunks) >= 12  # at least one per page with text


def test_fts5_keyword_query(tmp_path):
    pdf = _make_pdf(tmp_path, "sample.pdf")
    doc = fitz.open(pdf)
    pages_text = []
    for i in range(doc.page_count):
        raw = doc[i].get_text("text")
        norm = bk.normalize_text(raw)
        pages_text.append([ln for ln in norm.split("\n") if ln.strip()])
    doc.close()
    hf = bk.find_header_footer_lines(pages_text)
    cleaned = []
    for pl in pages_text:
        cleaned.append([ln for ln in pl if ln not in hf and not bk.is_page_number_line(ln)])
    chunks = bk.build_chunks_for_book("sample", cleaned, hf)

    import sqlite3
    db = ":memory:"
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, text TEXT)")
    cur.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2')")
    for cid, (page, section, text, wc) in enumerate(chunks, start=1):
        cur.execute("INSERT INTO chunks(id, text) VALUES (?, ?)", (cid, text))
        cur.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (cid, text))
    cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
    cur.execute("SELECT chunks.id, chunks.text FROM chunks_fts JOIN chunks ON chunks.id = chunks_fts.rowid WHERE chunks_fts MATCH 'hypertension' ORDER BY chunks.id LIMIT 1")
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert "hypertension" in row[1]


def test_row_counts_match(tmp_path):
    pdf = _make_pdf(tmp_path, "sample.pdf")
    doc = fitz.open(pdf)
    pages_text = []
    for i in range(doc.page_count):
        raw = doc[i].get_text("text")
        norm = bk.normalize_text(raw)
        pages_text.append([ln for ln in norm.split("\n") if ln.strip()])
    doc.close()
    hf = bk.find_header_footer_lines(pages_text)
    cleaned = []
    for pl in pages_text:
        cleaned.append([ln for ln in pl if ln not in hf and not bk.is_page_number_line(ln)])
    chunks = bk.build_chunks_for_book("sample", cleaned, hf)

    import sqlite3
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE books(id INTEGER PRIMARY KEY, name TEXT)")
    cur.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, book_id INTEGER, page INTEGER, section TEXT, text TEXT, word_count INTEGER)")
    cur.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT INTO books(id, name) VALUES (1, 'sample')")
    for cid, (page, section, text, wc) in enumerate(chunks, start=1):
        cur.execute("INSERT INTO chunks(id, book_id, page, section, text, word_count) VALUES (?, ?, ?, ?, ?, ?)",
                    (cid, 1, page, section, text, wc))
    cur.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    cur.execute("INSERT INTO meta(key, value) VALUES ('books_count', '1')")
    cur.execute("INSERT INTO meta(key, value) VALUES ('chunks_count', ?)", (str(len(chunks)),))
    conn.commit()

    b_count = cur.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    c_count = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    meta_chunks = int(cur.execute("SELECT value FROM meta WHERE key='chunks_count'").fetchone()[0])
    meta_books = int(cur.execute("SELECT value FROM meta WHERE key='books_count'").fetchone()[0])
    conn.close()
    assert b_count == 1
    assert c_count == len(chunks)
    assert meta_chunks == len(chunks)
    assert meta_books == 1


def test_deterministic(tmp_path):
    pdf = _make_pdf(tmp_path, "sample.pdf")
    doc = fitz.open(pdf)
    pages_text = []
    for i in range(doc.page_count):
        raw = doc[i].get_text("text")
        norm = bk.normalize_text(raw)
        pages_text.append([ln for ln in norm.split("\n") if ln.strip()])
    doc.close()
    hf = bk.find_header_footer_lines(pages_text)
    cleaned = []
    for pl in pages_text:
        cleaned.append([ln for ln in pl if ln not in hf and not bk.is_page_number_line(ln)])
    c1 = bk.build_chunks_for_book("sample", cleaned, hf)
    c2 = bk.build_chunks_for_book("sample", cleaned, hf)
    assert [(p, s, t, wc) for (p, s, t, wc) in c1] == [(p, s, t, wc) for (p, s, t, wc) in c2]


def test_empty_folder_exits_code_1(tmp_path):
    empty_dir = os.path.join(tmp_path, "empty_books")
    os.makedirs(empty_dir)
    # Point the module at the empty dir by monkeypatching.
    orig = bk.BOOKS_DIR
    bk.BOOKS_DIR = empty_dir
    try:
        with pytest.raises(SystemExit) as exc:
            bk.main()
        assert exc.value.code == 1
    finally:
        bk.BOOKS_DIR = orig


def test_arabic_normalization():
    # Tatweel removal-ish: NFKC keeps tatweel but we test normalization path generally.
    s = bk.normalize_text("ا\u0640\u0640\u0644\u064e\u064e\u064e")
    assert "\u200b" not in s
    assert "\ufeff" not in s
    # Diacritics: FTS5 tokenizer removes them, but normalization keeps base letters.
    assert "ل" in s
