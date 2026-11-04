#!/usr/bin/env python3
"""Generate manifest.txt for assets and stage small asset files for CI artifact."""
import os
import sys
import json
import hashlib
import sqlite3
import shutil
import numpy as np

ASSETS_DIR = os.path.join("app", "src", "main", "assets")
MANIFEST_DIR = os.path.join("eval", "assets_small")
MANIFEST_PATH = os.path.join(MANIFEST_DIR, "manifest.txt")


def compute_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate(out_dir=MANIFEST_DIR):
    os.makedirs(out_dir, exist_ok=True)
    manifest_file = os.path.join(out_dir, "manifest.txt")

    # Copy the 5 required small files into out_dir
    small_files = [
        "embedder_reference.json",
        "embeddings_meta.json",
        "normalize_map.json",
        "gate_config.json",
        "gate_reference.json",
    ]
    for sf in small_files:
        src = os.path.join(ASSETS_DIR, sf)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out_dir, sf))
        else:
            print(f"Notice: {src} not found during copy", file=sys.stderr)

    lines = []
    lines.append("=== ASSETS MANIFEST ===")
    lines.append("")
    lines.append("--- File Sizes and SHA-256 ---")

    for root, dirs, files in os.walk(ASSETS_DIR):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ASSETS_DIR)
            sz = os.path.getsize(p)
            sha = compute_sha256(p)
            lines.append(f"{rel}: size={sz} bytes, sha256={sha}")

    lines.append("")
    lines.append("--- Detailed Inspections ---")

    # books_knowledge.db inspection
    db_path = os.path.join(ASSETS_DIR, "books_knowledge.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # Exact .schema reproduction
        schema_lines = []
        for line in conn.iterdump():
            if line.startswith("CREATE "):
                schema_lines.append(line)
        schema_sql = "\n".join(schema_lines)
        
        chunk_count = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        schema_version = cur.execute("PRAGMA schema_version").fetchone()[0]
        
        cur.execute("SELECT text FROM chunks ORDER BY id")
        all_chunk_text = "".join(r[0] for r in cur.fetchall())
        chunk_texts_sha256 = hashlib.sha256(all_chunk_text.encode("utf-8")).hexdigest()
        conn.close()

        lines.append("books_knowledge.db:")
        lines.append(f"  chunk_count: {chunk_count}")
        lines.append(f"  schema_version: {schema_version}")
        lines.append(f"  chunk_texts_sha256: {chunk_texts_sha256}")
        lines.append("  .schema:")
        for sl in schema_sql.splitlines():
            lines.append(f"    {sl}")
    else:
        lines.append("books_knowledge.db: NOT FOUND")

    lines.append("")

    # embedder_reference.json inspection
    ref_path = os.path.join(ASSETS_DIR, "embedder_reference.json")
    if os.path.exists(ref_path):
        with open(ref_path, "r", encoding="utf-8") as f:
            ref_data = json.load(f)
        entries = ref_data.get("entries", ref_data) if isinstance(ref_data, dict) else ref_data
        num_entries = len(entries)
        vec_lengths = [len(e.get("vector", [])) for e in entries]
        lines.append("embedder_reference.json:")
        lines.append(f"  number of entries: {num_entries}")
        lines.append(f"  vector length of each entry: {vec_lengths}")
    else:
        lines.append("embedder_reference.json: NOT FOUND")

    lines.append("")

    # embeddings.bin inspection
    emb_path = os.path.join(ASSETS_DIR, "embeddings.bin")
    meta_path = os.path.join(ASSETS_DIR, "embeddings_meta.json")
    if os.path.exists(emb_path) and os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        arr = np.fromfile(emb_path, dtype=np.float32).reshape(meta["rows"], meta["dim"])
        lines.append("embeddings.bin:")
        lines.append(f"  shape: {arr.shape}")
    else:
        lines.append("embeddings.bin: NOT FOUND or meta missing")

    manifest_content = "\n".join(lines) + "\n"
    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(manifest_content)

    print(f"Generated {manifest_file} ({len(manifest_content)} bytes)")
    print("\n=== MANIFEST.TXT FULL CONTENT ===")
    print(manifest_content)
    print("=== END MANIFEST.TXT FULL CONTENT ===\n")
    return manifest_content


if __name__ == "__main__":
    content = generate()
    print("=== BEGIN MANIFEST.TXT ===")
    print(content)
    print("=== END MANIFEST.TXT ===")
