#!/usr/bin/env python3
"""
Verify that the release APK does NOT contain DesignGallery or any classes from the debug source set.
Stage UI-A requirement: "NO GALLERY IN RELEASE APK"
"""
import sys
import zipfile
import subprocess
import os

def check_apk(apk_path):
    print(f"Checking APK: {apk_path}")
    if not os.path.exists(apk_path):
        print(f"ERROR: APK not found at {apk_path}", file=sys.stderr)
        sys.exit(1)

    forbidden_terms = [b"DesignGallery", b"design/gallery", b"design.gallery"]
    found_violations = []

    with zipfile.ZipFile(apk_path, 'r') as z:
        for info in z.infolist():
            # Check file names in APK
            for term in [t.decode('utf-8') for t in forbidden_terms]:
                if term.lower() in info.filename.lower():
                    found_violations.append(f"Filename match in APK: {info.filename}")

            # Check inside DEX files
            if info.filename.endswith('.dex'):
                dex_data = z.read(info.filename)
                for term in forbidden_terms:
                    if term in dex_data:
                        found_violations.append(f"Found forbidden term '{term.decode('utf-8')}' in {info.filename}")

    # Check R8 mapping.txt if present
    mapping_path = "app/build/outputs/mapping/release/mapping.txt"
    if os.path.exists(mapping_path):
        with open(mapping_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if "DesignGallery" in line or "design.gallery" in line:
                    found_violations.append(f"Found gallery class in R8 mapping.txt: {line.strip()}")

    if found_violations:
        print("FAIL: Design gallery detected in release build!", file=sys.stderr)
        for v in found_violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    print("PASS: No gallery classes or references found in release APK or R8 mapping.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path_to_release_apk>")
        sys.exit(1)
    check_apk(sys.argv[1])
