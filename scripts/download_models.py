#!/usr/bin/env python3
"""Download multilingual-e5-small quantized ONNX model from Hugging Face Hub.

Downloads from repo Xenova/multilingual-e5-small:
  onnx/model_quantized.onnx
  tokenizer.json
  config.json

Saves into app/src/main/assets/models/embedder/.
Writes scripts/model_manifest.json with sha256 of each file and the repo revision.
Fails (exit 1) if any expected file is missing or download fails.
"""
import hashlib
import json
import os
import sys

from huggingface_hub import HfApi, hf_hub_download

REPO_ID = "Xenova/multilingual-e5-small"
EXPECTED_FILES = [
    "onnx/model_quantized.onnx",
    "tokenizer.json",
    "config.json",
]
OUT_DIR = os.path.join("app", "src", "main", "assets", "models", "embedder")
MANIFEST_PATH = os.path.join("scripts", "model_manifest.json")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def main():
    api = HfApi()

    # 1. List repo files and verify expected names exist.
    try:
        repo_files = list(api.list_repo_files(repo_id=REPO_ID))
    except Exception as exc:
        print(f"ERROR: Failed to list files for repo {REPO_ID}: {exc}", file=sys.stderr)
        sys.exit(1)

    repo_files_set = set(repo_files)
    missing = [f for f in EXPECTED_FILES if f not in repo_files_set]
    if missing:
        print(f"ERROR: The following expected files are missing from {REPO_ID}: {missing}", file=sys.stderr)
        print(f"Available files: {sorted(repo_files_set)}", file=sys.stderr)
        sys.exit(1)

    # 2. Get the repo revision (commit hash).
    try:
        repo_info = api.model_info(repo_id=REPO_ID)
        revision = repo_info.sha or repo_info.config or "unknown"
    except Exception as exc:
        print(f"ERROR: Failed to get repo info for {REPO_ID}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Repo: {REPO_ID} @ {revision}")
    print(f"Files to download: {EXPECTED_FILES}")

    # 3. Download each file.
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {
        "repo_id": REPO_ID,
        "revision": revision,
        "files": {},
    }

    for rel_path in EXPECTED_FILES:
        local_name = os.path.basename(rel_path)
        dest = os.path.join(OUT_DIR, local_name)
        print(f"Downloading {rel_path} -> {dest}")
        try:
            downloaded = hf_hub_download(
                repo_id=REPO_ID,
                filename=rel_path,
                revision=revision,
                local_dir=OUT_DIR,
                local_dir_use_symlinks=False,
            )
        except Exception as exc:
            print(f"ERROR: Download failed for {rel_path}: {exc}", file=sys.stderr)
            sys.exit(1)

        # hf_hub_download with local_dir puts the file at OUT_DIR/rel_path (preserving subdirs).
        # For onnx/model_quantized.onnx it lands at OUT_DIR/onnx/model_quantized.onnx;
        # we want it flattened at OUT_DIR/model_quantized.onnx. Handle both.
        actual = downloaded if os.path.exists(downloaded) else dest
        if not os.path.exists(actual):
            # Try the subdir layout HF creates under local_dir.
            candidate = os.path.join(OUT_DIR, rel_path)
            if os.path.exists(candidate):
                actual = candidate
        if not os.path.exists(actual):
            print(f"ERROR: Downloaded file not found at {actual}", file=sys.stderr)
            sys.exit(1)

        # Flatten: move to OUT_DIR/<basename>.
        final_dest = dest
        os.makedirs(os.path.dirname(final_dest), exist_ok=True)
        if os.path.abspath(actual) != os.path.abspath(final_dest):
            import shutil
            shutil.move(actual, final_dest)
            # Clean up empty subdirs left behind.
            subdir = os.path.join(OUT_DIR, "onnx")
            if os.path.isdir(subdir) and not os.listdir(subdir):
                os.rmdir(subdir)

        digest = sha256_file(final_dest)
        size = os.path.getsize(final_dest)

        # Verify against committed manifest if it exists.
        if os.path.exists(MANIFEST_PATH):
            with open(MANIFEST_PATH, "r", encoding="utf-8") as mf:
                committed = json.load(mf)
            committed_file = committed.get("files", {}).get(local_name)
            if committed_file:
                committed_sha = committed_file.get("sha256")
                if committed_sha and committed_sha != digest:
                    print(
                        f"ERROR: sha256 mismatch for {local_name}: "
                        f"committed={committed_sha}, downloaded={digest}",
                        file=sys.stderr,
                    )
                    sys.exit(1)

        manifest["files"][local_name] = {
            "sha256": digest,
            "size": size,
            "source": f"{REPO_ID}/{rel_path}@{revision}",
        }
        print(f"  {local_name}: {size} bytes, sha256={digest}")

    # Clean up any .cache directory created under OUT_DIR or its parents
    cache_dir = os.path.join(OUT_DIR, ".cache")
    if os.path.exists(cache_dir):
        import shutil
        shutil.rmtree(cache_dir, ignore_errors=True)

    # 4. Write manifest (committed).
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Manifest written to {MANIFEST_PATH}")
    print("Download complete.")


if __name__ == "__main__":
    main()
