#!/usr/bin/env python3
"""Build-time knowledge pipeline: PDF -> chunks -> embeddings -> FTS5 DB."""
import os, sys, json, sqlite3
import fitz  # PyMuPDF

def get_pages(pdf_path):
    doc = fitz.open(pdf_path)
    return [(i + 1, p.get_text()) for i, p in enumerate(doc)]

def main():
    books_dir = os.path.join("app", "src", "main", "assets", "books")
    out_db = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
    conn = sqlite3.connect(out_db)
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(text, book_name, page_number)")
    conn.commit()
    conn.close()
    print("built", out_db)

if __name__ == "__main__":
    main()
