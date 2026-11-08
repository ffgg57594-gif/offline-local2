#!/usr/bin/env python3
"""Stage 2: build-time knowledge DB from PDFs in app/src/main/assets/books/.
Reads every *.pdf, extracts per-page text, cleans, detects and skips non-content
pages (TOC / index / manual), chunks remaining pages, applies a chunk quality
guard, and writes app/src/main/assets/books_knowledge.db with FTS5.
Never packaged in the APK.
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone

BOOKS_DIR = os.path.join("app", "src", "main", "assets", "books")
OUT_DB = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
SKIP_FILE = os.path.join("scripts", "skip_pages.json")

ZERO_WIDTH = "\u200b\u200c\u200d\ufeff"

# Display-only cleanup for the Tofu squares that some PDF fonts leave behind.
# These code points are bullet glyphs or private-use/unassigned characters.
# The searchable ``text`` column is never changed; only ``display_text``.
# Input glyphs that we replace with the standard bullet U+2022.
DISPLAY_BULLET_CODEPOINTS = {
    0x2022, 0x2023, 0x2043, 0x2219, 0x25A0, 0x25A1, 0x25AA, 0x25AB,
    0x25CF, 0x25CB, 0x25E6, 0x25FE, 0x25FD, 0x25FC, 0x25FB,
}

# PDF tofu glyphs that must not survive in the display column. U+2022 itself
# is allowed because it is the replacement character.
DISPLAY_FORBIDDEN_CODEPOINTS = {
    0x2043, 0x2219, 0x25A0, 0x25A1, 0x25AA, 0x25AB,
    0x25CF, 0x25CB, 0x25E6, 0x25FE, 0x25FD, 0x25FC, 0x25FB,
}

_TOC_LABELS = {"contents", "table of contents", "المحتويات", "الفهرس"}
_DOT_LEADER = re.compile(r"\.{3,}|\u2026")
_PAGE_NUMBER_TAIL = re.compile(r".+\s+\d{1,4}\s*$")
_LINE_ENDING_IN_NUMBER = re.compile(r".*\d\s*$")
_INDEX_LINE = re.compile(r"^.+,\s*\d+(?:[-–]\d+)?(?:\s*,\s*\d+(?:[-–]\d+)?)*\s*$")
_SENTENCE_END = re.compile(r"[.!?؟۔]$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def normalize_text(text):
    """NFKC, strip zero-width chars, collapse whitespace.

    Used for page-text cleaning (header/footer detection, chunking).
    Case is preserved because header/footer detection is case-sensitive.
    """
    text = unicodedata.normalize("NFKC", text)
    for ch in ZERO_WIDTH:
        text = text.replace(ch, "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    cleaned_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    return "\n".join(cleaned_lines)


def normalize_search_text(text):
    """Normalize text for FTS5 search_text column.

    Lowercases and unifies hyphens so that indexing-time and query-time
    normalization are consistent with text_normalize.normalize_text
    (without variant map, which is built later from the corpus).
    """
    text = normalize_text(text)
    text = text.lower()
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", text)
    return text


def is_replaceable_display_char(ch):
    """True for input glyphs that the display pass should replace."""
    cp = ord(ch)
    if cp in DISPLAY_BULLET_CODEPOINTS:
        return True
    return unicodedata.category(ch) in ("Co", "Cn", "Cs")


def is_bad_display_char(ch):
    """True for Tofu/private-use/unassigned chars after the display pass.

    U+2022 (the inserted standard bullet) is deliberately allowed.
    """
    cp = ord(ch)
    if cp in DISPLAY_FORBIDDEN_CODEPOINTS:
        return True
    return unicodedata.category(ch) in ("Co", "Cn", "Cs")


def display_text(text):
    """Return a UI-only copy of ``text`` with Tofu squares removed.

    Bullet glyphs, private-use characters and unassigned code points become
    the standard bullet ``• ``. Runs of spaces are collapsed. The original
    ``text`` (and therefore ``chunk_texts_sha256``) is left untouched.
    """
    out = []
    for ch in text:
        out.append("• " if is_replaceable_display_char(ch) else ch)
    cleaned = "".join(out)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def has_bad_display_char(text):
    return any(is_bad_display_char(ch) for ch in text)


def dehyphenate(text):
    """Join a word split at a line end: 'diagno-\nsis' -> 'diagnosis'."""
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def split_into_paragraphs(text):
    """Blank lines separate paragraphs."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def is_page_number_line(line):
    return bool(re.match(r"^\s*\d{1,6}\s*$", line.strip()))


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


def letter_ratio(text):
    """Ratio of letters (Latin or Arabic, any Unicode letter) to total non-space chars."""
    non_space = [ch for ch in text if not ch.isspace()]
    if not non_space:
        return 0.0
    letters = sum(1 for ch in non_space if unicodedata.category(ch)[0] == "L")
    return letters / len(non_space)


def has_sentence(text):
    """True if the text contains at least one sentence-ending line."""
    return bool(_SENTENCE_END.search(text.strip()))


def word_count(text):
    return len(text.split())


def is_toc_page(lines):
    """Table-of-contents page detection."""
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return False
    # Line equals a TOC label and page has >= 5 lines ending in numbers.
    first = non_empty[0].strip().lower()
    if first in _TOC_LABELS:
        num_ending = sum(1 for ln in non_empty if _LINE_ENDING_IN_NUMBER.match(ln.strip()))
        if num_ending >= 5:
            return True
    # At least 35% of non-empty lines contain a dot leader or end with a page number.
    leader_or_tail = 0
    for ln in non_empty:
        s = ln.strip()
        if _DOT_LEADER.search(s) or _PAGE_NUMBER_TAIL.match(s):
            leader_or_tail += 1
    if leader_or_tail / len(non_empty) >= 0.35:
        return True
    return False


def is_index_page(lines):
    """Index page: >= 50% of lines match term, comma-separated page numbers."""
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return False
    matches = sum(1 for ln in non_empty if _INDEX_LINE.match(ln.strip()))
    return matches / len(non_empty) >= 0.50


def is_short_garbage_page(lines):
    """Page with fewer than 15 words and no sentence -> likely garbage / section divider."""
    text = " ".join(lines)
    return word_count(text) < 15 and not has_sentence(text)


def load_skip_pages():
    """Load manual skip overrides from scripts/skip_pages.json."""
    if not os.path.exists(SKIP_FILE):
        return {}
    try:
        with open(SKIP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): list(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def split_paragraph_at_sentences(paragraph, max_words=180):
    parts = re.split(r"(?<=[.!?؟.])\s+|\n", paragraph)
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
    words = line.split()
    if len(words) >= 12:
        return False
    if line.rstrip().endswith((".", "!", "?", "؟", "۔")):
        return False
    if not next_line:
        return False
    if len(next_line.split()) <= len(words) + 2:
        return False
    return bool(re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF0-9 ,;:&()\-\"\']{1,80}$").match(line.strip()))


def build_chunks_for_book(book_name, pages_text, header_footer_lines, skip_pages):
    """Return list of (page, section, text, word_count) in page order, skipping skip_pages."""
    chunks = []
    current_section = ""
    skip_set = set(skip_pages)
    for page_idx, page_lines in enumerate(pages_text, start=1):
        if page_idx in skip_set:
            continue
        page_text = "\n".join(page_lines)
        page_text = dehyphenate(page_text)
        paragraphs = split_into_paragraphs(page_text)
        if not paragraphs:
            continue
        para_texts = [p for p in paragraphs]
        for i, para in enumerate(para_texts):
            first_line = para.split("\n")[0] if "\n" in para else para
            next_para = para_texts[i + 1] if i + 1 < len(para_texts) else ""
            if is_heading_like(first_line, next_para):
                current_section = first_line.strip()
        page_chunks = chunk_paragraphs(para_texts, current_section, page_idx)
        chunks.extend(page_chunks)
    return chunks


def chunk_paragraphs(paragraphs, section, page_idx):
    out = []
    target_min, target_max = 100, 180
    overlap = int(target_max * 0.20)
    buffer_words = []
    buffer_text = ""
    for para in paragraphs:
        words = para.split()
        if len(words) < 20:
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
                    buffer_words = buffer_words[-overlap:] if overlap else []
                    buffer_text = " ".join(buffer_words)
                continue
            else:
                if buffer_words:
                    out.append((page_idx, section, buffer_text, len(buffer_words)))
                buffer_words = words[:]
                buffer_text = para
                continue
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

    manual_skips = load_skip_pages()

    os.makedirs(os.path.dirname(OUT_DB), exist_ok=True)
    if os.path.exists(OUT_DB):
        os.remove(OUT_DB)

    conn = sqlite3.connect(OUT_DB)
    cur = conn.cursor()
    cur.execute("CREATE TABLE books(id INTEGER PRIMARY KEY, name TEXT, sha256 TEXT, pages INTEGER)")
    cur.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, book_id INTEGER, page INTEGER, section TEXT, text TEXT, display_text TEXT, search_text TEXT, word_count INTEGER)")
    cur.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(search_text, content='chunks', content_rowid='id', tokenize='porter unicode61 remove_diacritics 2')")
    cur.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")

    chunk_id = 1
    total_chunks_before_guard = 0
    total_chunks_after_guard = 0
    total_dropped = 0
    display_changed = 0
    display_bad = 0
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
            raw = doc[i].get_text("text")
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

        # --- Non-content page detection ---
        skip_reasons = {}  # page -> reason
        manual_for_book = set(manual_skips.get(book_name, []))
        for page_idx, page_lines in enumerate(pages_text, start=1):
            if page_idx in manual_for_book:
                skip_reasons[page_idx] = "manual"
                continue
            if is_toc_page(page_lines):
                skip_reasons[page_idx] = "toc"
                continue
            if is_index_page(page_lines):
                skip_reasons[page_idx] = "index"
                continue
            if is_short_garbage_page(page_lines):
                skip_reasons[page_idx] = "short"
                continue

        # Clean header/footer and page-number lines from remaining pages.
        cleaned_pages = []
        for page_idx, page_lines in enumerate(pages_text, start=1):
            if page_idx in skip_reasons:
                cleaned_pages.append([])
                continue
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

        book_chunks = build_chunks_for_book(book_name, cleaned_pages, hf_lines, set(skip_reasons.keys()))

        # --- Chunk quality guard ---
        kept_chunks = []
        dropped = 0
        for page, section, text, wc in book_chunks:
            if letter_ratio(text) < 0.6:
                dropped += 1
                continue
            kept_chunks.append((page, section, text, wc))

        cur.execute("INSERT INTO books(name, sha256, pages) VALUES (?, ?, ?)",
                    (book_name, file_sha, page_count))
        book_id = cur.lastrowid

        for page, section, text, wc in kept_chunks:
            search_text = normalize_search_text(text)
            shown = display_text(text)
            if shown != text:
                display_changed += 1
            if has_bad_display_char(shown):
                display_bad += 1
            cur.execute(
                "INSERT INTO chunks(id, book_id, page, section, text, display_text, search_text, word_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk_id, book_id, page, section, text, shown, search_text, wc),
            )
            cur.execute("INSERT INTO chunks_fts(rowid, search_text) VALUES (?, ?)", (chunk_id, search_text))
            chunk_id += 1

        total_chunks_before_guard += len(book_chunks)
        total_chunks_after_guard += len(kept_chunks)
        total_dropped += dropped

        # Record skipped pages in meta.
        if skip_reasons:
            pages_sorted = sorted(skip_reasons.keys())
            cur.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                (f"skipped_pages_{book_id}", ",".join(str(p) for p in pages_sorted)),
            )
            for p, r in skip_reasons.items():
                cur.execute(
                    "INSERT INTO meta(key, value) VALUES (?, ?)",
                    (f"skip_reason_p{book_id}_{p}", r),
                )

        avg_wc = (sum(c[3] for c in kept_chunks) / len(kept_chunks)) if kept_chunks else 0.0
        skipped_list = ", ".join(f"{p}({r})" for p, r in sorted(skip_reasons.items())) or "-"
        summary_rows.append(
            (book_name, page_count, pages_with_text, len(book_chunks) + dropped, len(kept_chunks),
             round(avg_wc, 1), dropped, skipped_list)
        )
        books_rows.append(book_name)
        doc.close()

    cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")

    build_time = datetime.now(timezone.utc).isoformat()
    cur.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
    cur.execute("INSERT INTO meta(key, value) VALUES ('build_time', ?)", (build_time,))
    cur.execute("INSERT INTO meta(key, value) VALUES ('books_count', ?)", (len(books_rows),))
    cur.execute("INSERT INTO meta(key, value) VALUES ('chunks_before_guard', ?)", (total_chunks_before_guard,))
    cur.execute("INSERT INTO meta(key, value) VALUES ('chunks_after_guard', ?)", (total_chunks_after_guard,))
    cur.execute("INSERT INTO meta(key, value) VALUES ('chunks_dropped_guard', ?)", (total_dropped,))
    cur.execute("INSERT INTO meta(key, value) VALUES ('display_text_changed', ?)", (display_changed,))
    cur.execute("INSERT INTO meta(key, value) VALUES ('display_text_bad', ?)", (display_bad,))

    conn.commit()
    conn.close()

    # Summary table
    header = "| Book | Pages | Pages w/ text | Chunks before | Chunks after | Avg words/chunk | Dropped guard | Skipped pages |"
    sep = "|" + "|".join("---" for _ in range(9)) + "|"
    lines = [header, sep]
    for name, pg, pwt, cb, ca, avg, dr, sk in summary_rows:
        lines.append(f"| {name} | {pg} | {pwt} | {cb} | {ca} | {avg} | {dr} | {sk} |")
    table = "\n".join(lines)
    print(table)
    print(
        f"display_text_changed={display_changed}/{total_chunks_after_guard} "
        f"display_text_bad={display_bad}"
    )
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("## Book knowledge DB build summary\n\n")
            f.write(table + "\n\n")
            f.write(
                f"display_text_changed={display_changed}/{total_chunks_after_guard}, "
                f"display_text_bad={display_bad}\n\n"
            )


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
