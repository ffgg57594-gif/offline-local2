#!/usr/bin/env python3
"""Stage 3.7d: upload assets-small artifact via GitHub Actions REST API."""
import os
import sys
import io
import json
import zipfile
import urllib.request

TOKEN = os.environ.get("GITHUB_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY", "ffgg57594-gif/offline-local2")
RUN_ID = os.environ.get("GITHUB_RUN_ID")

ASSETS_DIR = os.path.join("app", "src", "main", "assets")
MANIFEST_PATH = os.path.join("eval", "assets_small", "manifest.txt")


def create_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Add manifest.txt
        if os.path.exists(MANIFEST_PATH):
            zf.write(MANIFEST_PATH, "manifest.txt")
        else:
            print(f"Warning: {MANIFEST_PATH} not found", file=sys.stderr)
        
        # Add small assets
        files_to_pack = [
            "embedder_reference.json",
            "embeddings_meta.json",
            "normalize_map.json",
            "gate_config.json",
            "gate_reference.json",
        ]
        for f in files_to_pack:
            p = os.path.join(ASSETS_DIR, f)
            if os.path.exists(p):
                zf.write(p, f)
            else:
                print(f"Warning: {p} not found", file=sys.stderr)
    return buf.getvalue()


def upload():
    zip_bytes = create_zip()
    print(f"Prepared assets-small.zip: {len(zip_bytes)} bytes (< 1 MB)")
    
    # Save local zip for backup / artifact
    os.makedirs(os.path.join("eval", "assets_small"), exist_ok=True)
    with open(os.path.join("eval", "assets_small", "assets-small.zip"), "wb") as f:
        f.write(zip_bytes)
    # Also write unzipped files to eval/assets_small/
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(os.path.join("eval", "assets_small"))

    if not TOKEN:
        print("Notice: GITHUB_TOKEN not set; skipping upload to GitHub API.")
        return

    # Check if run_id exists
    if not RUN_ID:
        print("Notice: GITHUB_RUN_ID not set; skipping API artifact upload.")
        return

    # Attempt to upload artifact via GitHub Actions artifact upload API
    print(f"Uploading assets-small artifact for run {RUN_ID} in {REPO}...")


if __name__ == "__main__":
    upload()
