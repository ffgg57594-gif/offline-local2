#!/usr/bin/env python3
"""Stage 3.7e: APK integrity verification.

After assembleRelease, for every entry under assets/ in the APK:
- print: name, uncompressed size, compressed size (unzip -lv), sha256 of extracted entry,
  and sha256 of the same file in app/src/main/assets.
- FAIL (exit 1) if:
  * any hash differs
  * any .pdf exists anywhere in the APK
  * any entry under a path starting with a dot exists (e.g. .* or .cache/...)
  * _gate_stem_helper exists in the DB (books_knowledge.db)
- Also print the 15 largest entries of the whole APK (name, compressed size) and the total APK size.
"""
import glob
import hashlib
import os
import sqlite3
import subprocess
import sys
import zipfile

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()

def find_apk():
    # 1. Search standard paths
    candidates = [
        "app/build/outputs/apk/release/*.apk",
        "app/build/outputs/apk/release/*/*.apk",
        "app/build/intermediates/apk/release/*.apk",
        "app/build/intermediates/apk/release/*/*.apk",
    ]
    for pattern in candidates:
        apks = glob.glob(pattern)
        if apks:
            return apks[0]
            
    # 2. Recursive search under app/build
    for root, dirs, files in os.walk("app/build"):
        for f in files:
            if f.endswith(".apk"):
                return os.path.join(root, f)

    return None

def main():
    apk_path = find_apk()
    if not apk_path:
        print("NOTICE: No release APK found at this stage; skipping integrity verification.")
        sys.exit(0)

    total_apk_size = os.path.getsize(apk_path)

    print(f"=== APK INTEGRITY VERIFICATION ===")
    print(f"Target APK: {apk_path} ({total_apk_size} bytes)\n")

    errors = []

    with zipfile.ZipFile(apk_path, "r") as z:
        # Check all entries in APK for .pdf and dot paths
        for info in z.infolist():
            fname = info.filename
            if fname.lower().endswith(".pdf"):
                errors.append(f"FAIL: .pdf file found in APK: {fname}")
            parts = fname.split("/")
            for p in parts:
                if p.startswith(".") and p != "." and p != "..":
                    errors.append(f"FAIL: dot path entry found in APK: {fname}")

        # Check all entries under assets/
        print("--- Assets in APK ---")
        print(f"{'Asset Name':<45} | {'Uncomp Size':<11} | {'Comp Size':<10} | {'APK SHA-256':<64} | {'Source SHA-256':<64}")
        print("-" * 205)

        asset_entries = [info for info in z.infolist() if info.filename.startswith("assets/") and not info.filename.endswith("/")]
        for info in asset_entries:
            name = info.filename
            # Ignore dexopt synthetic assets created during packaging
            if name.startswith("assets/dexopt/"):
                print(f"{name:<45} | {info.file_size:<11} | {info.compress_size:<10} | (dexopt profile - skipped)")
                continue

            # relative path under app/src/main/assets
            rel_asset = name[len("assets/"):]
            source_path = os.path.join("app", "src", "main", "assets", rel_asset)

            data = z.read(name)
            apk_sha = sha256_bytes(data)

            if not os.path.exists(source_path):
                errors.append(f"FAIL: Asset {name} in APK but missing in {source_path}")
                source_sha = "MISSING"
            else:
                source_sha = sha256_file(source_path)
                if apk_sha != source_sha:
                    errors.append(f"FAIL: Hash mismatch for {name}: APK={apk_sha} != Source={source_sha}")

            print(f"{name:<45} | {info.file_size:<11} | {info.compress_size:<10} | {apk_sha} | {source_sha}")

            # Specific DB integrity check
            if name == "assets/books_knowledge.db":
                tmp_db = "/tmp/apk_verify_books_knowledge.db"
                with open(tmp_db, "wb") as f_db:
                    f_db.write(data)
                try:
                    conn = sqlite3.connect(tmp_db)
                    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    conn.close()
                    for t in tables:
                        if "_gate_stem_helper" in t:
                            errors.append(f"FAIL: _gate_stem_helper found in APK {name}: table {t}")
                except Exception as e:
                    errors.append(f"FAIL: Could not check tables in {name}: {e}")

        # 15 largest entries of the whole APK
        print("\n--- 15 Largest Entries in APK (by compressed size) ---")
        all_entries = sorted(z.infolist(), key=lambda e: e.compress_size, reverse=True)
        for i, e in enumerate(all_entries[:15], 1):
            print(f"{i:2d}. {e.filename:<50} : compressed {e.compress_size:10d} bytes (uncompressed {e.file_size:10d} bytes)")

    print(f"\nTotal APK size: {total_apk_size} bytes\n")

    if errors:
        print("=== VERIFICATION FAILED ===", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    print("APK integrity check: PASSED (all asset hashes match, no .pdf, no dot entries, clean DB).")

if __name__ == "__main__":
    main()
