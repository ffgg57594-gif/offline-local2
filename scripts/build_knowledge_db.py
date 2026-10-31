#!/usr/bin/env python3
"""Stage 2: build-time knowledge DB from PDFs in app/src/main/assets/books/.
Reads every *.pdf, extracts per-page text, cleans, chunks, and writes
app/src/main/assets/books_knowledge.db with FTS5. Never packaged in the APK.
"""
import hashlib
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone

BOOKS_DIR = os.path.join("app", "src", "main", "assets", "books")
OUT_DB = os.path.join("app", "src", "main", "assets", "books_knowledge.db")

ZERO_WIDTH = "\u200b\u200c\u200d\ufeff"
_HEADING_LINE_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF0-9 ,;:&()\-\"\']{1,80}$")
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,6}\s*$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def normalize_text(text):
    """NFKC, strip zero-width chars, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    for ch in ZERO_WIDTH:
        text = text.replace(ch, "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse horizontal whitespace inside lines, keep newlines as paragraph separators.
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line).strip()
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def dehyphenate(text):
    """Join a word split at a line end: 'diagno-\nsis' -> 'diagnosis'."""
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def split_into_paragraphs(text):
    """Blank lines separate paragraphs."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def is_page_number_line(line):
    return bool(_PAGE_NUMBER_RE.match(line.strip()))


def find_header_footer_lines(pages_text, min_pages=10, threshold=0.4):
    """Lines (trimmed) appearing on more than `threshold` of pages.
    Only when the book has at least min_pages pages."""
    if len(pages_text) < min_pages:
        return set()
    counts = {}
    for page_lines in pages_text:
        seen = set()
        for line in page_lines:
            tl = line.strip()
            if tl and tl not in seen:
                counts[tl] = counts.get(tl, 0) + 1
                seen.add(tl)
    total = len(pages_text)
    return {line for line, c in counts.items() if c / total > threshold}


def split_paragraph_at_sentences(paragraph, max_words=180):
    """Split a long paragraph at sentence boundaries (. ! ? ؟ ۔ newline)."""
    # Keep sentence terminators with the preceding text.
    parts = re.split(r"(?<=[.!?؟۔])\s+|\n", paragraph)
    chunks_out = []
    current = []
    current_words = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        words = part.split()
        if current_words + len(words) > max_words and current:
            chunks_out.append(" ".join(current))
            current = []
            current_words = 0
        current.append(part)
        current_words += len(words)
    if current:
        chunks_out.append(" ".join(current))
    return chunks_out


def is_heading_like(line, next_line):
    """Short line (<12 words), no final period, followed by a longer paragraph."""
    words = line.split()
    if len(words) >= 12:
        return False
    if line.rstrip().endswith((".", "!", "?", "؟", "۔")):
        return False
    if not next_line:
        return False
    # Heading should be clearly shorter than the following paragraph.
    if len(next_line.split()) <= len(words) + 2:
        return False
    return bool(_HEADING_LINE_RE.match(line.strip()))


def build_chunks_for_book(book_name, pages_text, header_footer_lines):
    """Return list of (page, section, text, word_count) in page order."""
    chunks = []
    current_section = ""
    for page_idx, page_lines in enumerate(pages_text, start=1):
        page_text = "\n".join(page_lines)
        page_text = dehyphenate(page_text)
        paragraphs = split_into_paragraphs(page_text)
        if not paragraphs:
            continue
        # Track headings within this page.
        para_texts = [p for p in paragraphs]
        for i, para in enumerate(para_texts):
            first_line = para.split("\n")[0] if "\n" in para else para
            next_para = para_texts[i + 1] if i + 1 < len(para_texts) else ""
            if is_heading_like(first_line, next_para):
                current_section = first_line.strip()
        # Chunk paragraphs on this page only (no crossing page boundary).
        page_chunks = chunk_paragraphs(para_texts, current_section, page_idx)
        chunks.extend(page_chunks)
    return chunks


def chunk_paragraphs(paragraphs, section, page_idx):
    """Create chunks of ~100-180 words with 20% overlap, never crossing a page."""
    out = []
    target_min, target_max = 100, 180
    overlap = int(target_max * 0.20)  # ~36 words overlap
    buffer_words = []
    buffer_text = ""
    for para in paragraphs:
        words = para.split()
        if len(words) < 20:
            # Very short paragraph: merge into buffer or standalone.
            if buffer_words and len(buffer_words) + len(words) <= target_max:
                buffer_words.extend(words)
                buffer_text = (buffer_text + " " + para).strip()
            else:
                if buffer_words:
                    out.append((page_idx, section, buffer_text, len(buffer_words)))
                    buffer_words = []
                    buffer_text = ""
                out.append((page_idx, section, para, len(words)))
            continue
        if len(words) <= target_max:
            if buffer_words and len(buffer_words) + len(words) <= target_max:
                buffer_words.extend(words)
                buffer_text = (buffer_text + " " + para).strip()
                if len(buffer_words) >= target_min:
                    out.append((page_idx, section, buffer_text, len(buffer_words)))
                    # Keep overlap words for next chunk.
                    buffer_words = buffer_words[-overlap:] if overlap else []
                    buffer_text = " ".join(buffer_words)
                continue
            else:
                if buffer_words:
                    out.append((page_idx, section, buffer_text, len(buffer_words)))
                buffer_words = words[:]
                buffer_text = para
                continue
        # Paragraph longer than max: split at sentence boundaries.
        if buffer_words:
            out.append((page_idx, section, buffer_text, len(buffer_words)))
            buffer_words = []
            buffer_text = ""
        for sub in split_paragraph_at_sentences(para, max_words=target_max):
            sw = sub.split()
            if len(sw) < 20 and buffer_words:
                buffer_words.extend(sw)
                buffer_text = (buffer_text + " " + sub).strip()
                continue
            if buffer_words:
                out.append((page_idx, section, buffer_text, len(buffer_words)))
            buffer_words = sw[:]
            buffer_text = sub
            if len(buffer_words) >= target_min:
                out.append((page_idx, section, buffer_text, len(buffer_words)))
                buffer_words = buffer_words[-overlap:] if overlap else []
                buffer_text = " ".join(buffer_words)
    if buffer_words:
        out.append((page_idx, section, buffer_text, len(buffer_words)))
    return out


def build_db(pdf_paths):
    if not pdf_paths:
        print("ERROR: No PDF files found in " + BOOKS_DIR, file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(OUT_DB), exist_ok=True)
    if os.path.exists(OUT_DB):
        os.remove(OUT_DB)

    conn = sqlite3.connect(OUT_DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE books(
            id INTEGER PRIMARY KEY,
            name TEXT,
            sha256 TEXT,
            pages INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE chunks(
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            page INTEGER,
            section TEXT,
            text TEXT,
            word_count INTEGER
        )
    """)
    cur.execute("""
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            text,
            content='chunks',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    cur.execute("""
        CREATE TABLE meta(
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    chunk_id = 1
    total_chunks = 0
    books_rows = []
    summary_rows = []

    for pdf_path in sorted(pdf_paths, key=lambda p: os.path.basename(p).lower()):
        book_name = os.path.splitext(os.path.basename(pdf_path))[0]
        file_sha = sha256_file(pdf_path)

        import fitz
        doc = fitz.open(pdf_path)
        page_count = doc.page_count
        pages_text = []
        pages_with_text = 0
        empty_pages = []

        for i in range(page_count):
            page = doc[i]
            raw = page.get_text("text")
            norm = normalize_text(raw)
            lines = [ln for ln in norm.split("\n") if ln.strip()]
            pages_text.append(lines)
            if norm.strip():
                pages_with_text += 1
            else:
                empty_pages.append(i + 1)

        if pages_with_text == 0:
            doc.close()
            print(
                f"ERROR: '{book_name}' has zero extractable text (probably scanned). "
                f"OCR is not supported in this stage.",
                file=sys.stderr,
            )
            sys.exit(1)

        if empty_pages:
            print(
                f"WARNING: '{book_name}' has pages with no extractable text: "
                f"{', '.join(str(p) for p in empty_pages)}",
                file=sys.stderr,
            )

        hf_lines = find_header_footer_lines(pages_text)

        cleaned_pages = []
        for page_lines in pages_text:
            cleaned = []
            for line in page_lines:
                tl = line.strip()
                if not tl:
                    continue
                if tl in hf_lines:
                    continue
                if is_page_number_line(tl):
                    continue
                cleaned.append(tl)
            cleaned_pages.append(cleaned)

        book_chunks = build_chunks_for_book(book_name, cleaned_pages, hf_lines)

        cur.execute("INSERT INTO books(name, sha256, pages) VALUES (?, ?, ?)",
                    (book_name, file_sha, page_count))
        book_id = cur.lastrowid

        for page, section, text, wc in book_chunks:
            cur.execute(
                "INSERT INTO chunks(id, book_id, page, section, text, word_count) VALUES (?, ?, ?, ?, ?, ?)",
                (chunk_id, book_id, page, section, text, wc),
            )
            cur.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (chunk_id, text))
            chunk_id += 1

        total_chunks += len(book_chunks)
        avg_wc = (sum(c[3] for c in book_chunks) / len(book_chunks)) if book_chunks else 0.0
        summary_rows.append((book_name, page_count, pages_with_text, len(book_chunks), round(avg_wc, 1)))
        books_rows.append(book_name)
        doc.close()

    cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")

    build_time = datetime.now(timezone.utc).isoformat()
    cur.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    cur.execute("INSERT INTO meta(key, value) VALUES ('build_time', ?)", (build_time,))
    cur.execute("INSERT INTO meta(key, value) VALUES ('books_count', ?)", (len(books_rows),))
    cur.execute("INSERT INTO meta(key, value) VALUES ('chunks_count', ?)", (total_chunks,))

    conn.commit()
    conn.close()

    # Summary table
    header = f"| Book | Pages | Pages with text | Chunks | Avg words/chunk |"
    sep = "|" + "|".join("---" for _ in range(6)) + "|"
    lines = [header, sep]
    for name, pg, pwt, ch, avg in summary_rows:
        lines.append(f"| {name} | {pg} | {pwt} | {ch} | {avg} |")
    table = "\n".join(lines)
    print(table)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("## Book knowledge DB build summary\n\n")
            f.write(table + "\n\n")


def main():
    if not os.path.isdir(BOOKS_DIR):
        print(f"ERROR: Books folder not found: {BOOKS_DIR}", file=sys.stderr)
        sys.exit(1)
    pdf_paths = [
        os.path.join(BOOKS_DIR, f)
        for f in os.listdir(BOOKS_DIR)
        if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(BOOKS_DIR, f))
    ]
    build_db(pdf_paths)


if __name__ == "__main__":
    main()
