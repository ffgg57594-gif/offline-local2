#!/usr/bin/env python3
"""Stage K1: generate app/src/main/assets/assets_manifest.json

Writes manifest for all shipped assets:
- name (relative to assets root, forward slashes)
- size (bytes)
- sha256 (lowercase hex)
Also includes top-level metadata:
- chunk_count
- chunk_texts_sha256
"""
import hashlib
import json
import os
import sqlite3
import sys

ASSETS_DIR = os.path.join("app", "src", "main", "assets")
MANIFEST_OUT = os.path.join(ASSETS_DIR, "assets_manifest.json")
DB_PATH = os.path.join(ASSETS_DIR, "books_knowledge.db")


def compute_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    if not os.path.exists(ASSETS_DIR):
        print(f"ERROR: {ASSETS_DIR} not found", file=sys.stderr)
        sys.exit(1)

    # 1. Inspect DB for chunk_count and chunk_texts_sha256
    chunk_count = 0
    chunk_texts_sha256 = ""
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        chunk_count = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        cur.execute("SELECT text FROM chunks ORDER BY id")
        all_text = "".join(r[0] for r in cur.fetchall())
        chunk_texts_sha256 = hashlib.sha256(all_text.encode("utf-8")).hexdigest()
        conn.close()
    else:
        print(f"WARNING: {DB_PATH} not found", file=sys.stderr)

    # 2. Gather shipped asset files
    # Note: books/ contains the raw PDF which is excluded from the APK (!books)
    # Exclude assets_manifest.json itself if already present
    entries = []
    for root, dirs, files in os.walk(ASSETS_DIR):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ASSETS_DIR).replace("\\", "/")
            if rel == "assets_manifest.json":
                continue
            if rel.startswith("books/") or rel == "books":
                continue
            if rel == "models/embedder/tokenizer.json":
                continue
            if rel.startswith("."):
                continue
            sz = os.path.getsize(p)
            sha = compute_sha256(p)
            entries.append({
                "name": rel,
                "size": sz,
                "sha256": sha
            })

    entries.sort(key=lambda x: x["name"])

    manifest_data = {
        "chunk_count": chunk_count,
        "chunk_texts_sha256": chunk_texts_sha256,
        "assets": entries
    }

    with open(MANIFEST_OUT, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
        f.write("\n")

    manifest_sha256 = compute_sha256(MANIFEST_OUT)
    print(f"Wrote {MANIFEST_OUT} with {len(entries)} assets.")
    print(f"chunk_count: {chunk_count}")
    print(f"chunk_texts_sha256: {chunk_texts_sha256}")
    print(f"assets_manifest.json sha256: {manifest_sha256}")
    print(f"manifest prefix (12 chars): {manifest_sha256[:12]}")


if __name__ == "__main__":
    main()
