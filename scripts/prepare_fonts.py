#!/usr/bin/env python3
"""Downloads, subsets and installs IBM Plex Sans Arabic and Source Serif 4 fonts."""
import io
import os
import pathlib
import ssl
import subprocess
import urllib.request
import zipfile

ctx = ssl.create_default_context(cafile='/etc/ssl/certs/ca-certificates.crt')
ROOT = pathlib.Path(__file__).resolve().parents[1]
font_dir = ROOT / "app/src/main/res/font"
font_dir.mkdir(parents=True, exist_ok=True)
lic_dir = ROOT / "docs/licenses"
lic_dir.mkdir(parents=True, exist_ok=True)

ibm_base = "https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsansarabic"
ibm_files = {
    "ibm_plex_sans_arabic_regular.ttf": f"{ibm_base}/IBMPlexSansArabic-Regular.ttf",
    "ibm_plex_sans_arabic_medium.ttf": f"{ibm_base}/IBMPlexSansArabic-Medium.ttf",
    "ibm_plex_sans_arabic_bold.ttf": f"{ibm_base}/IBMPlexSansArabic-Bold.ttf",
}

print("Fetching IBM Plex Sans Arabic license...")
req = urllib.request.Request(f"{ibm_base}/OFL.txt", headers={"User-Agent": "Python"})
with urllib.request.urlopen(req, context=ctx) as r:
    (lic_dir / "OFL-IBM-Plex-Sans-Arabic.txt").write_bytes(r.read())

unicodes_arabic = "U+0020-007E,U+00A0-00FF,U+0100-017F,U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+2000-206F,U+2070-209F,U+20A0-20CF,U+2190-21FF,U+25A0-25FF"

for dest_name, url in ibm_files.items():
    print(f"Downloading {dest_name}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Python"})
    with urllib.request.urlopen(req, context=ctx) as r:
        raw_data = r.read()
    temp_raw = f"/tmp/{dest_name}.raw.ttf"
    with open(temp_raw, "wb") as f:
        f.write(raw_data)
    dest_path = font_dir / dest_name
    cmd = [
        "pyftsubset",
        temp_raw,
        f"--output-file={dest_path}",
        f"--unicodes={unicodes_arabic}",
        "--layout-features=*",
        "--glyph-names",
        "--symbol-cmap",
        "--legacy-cmap",
        "--notdef-glyph",
        "--notdef-outline",
        "--recommended-glyphs",
    ]
    subprocess.check_call(cmd)
    orig_sz = len(raw_data)
    sub_sz = dest_path.stat().st_size
    print(f"  {dest_name}: {orig_sz} -> {sub_sz} bytes ({sub_sz/1024:.1f} KB)")
    os.remove(temp_raw)

serif_url = "https://github.com/adobe-fonts/source-serif/releases/download/4.005R/source-serif-4.005_Desktop.zip"
print(f"Downloading Source Serif 4 release zip from {serif_url}...")
req = urllib.request.Request(serif_url, headers={"User-Agent": "Python"})
with urllib.request.urlopen(req, context=ctx) as r:
    zip_bytes = r.read()

unicodes_latin = "U+0020-007E,U+00A0-00FF,U+0100-024F,U+0370-03FF,U+2000-206F,U+2010-2027,U+2030-205E,U+2070-209F,U+20A0-20CF,U+2190-21FF,U+2200-22FF,U+25A0-25FF"

serif_map = {
    "source-serif-4.005_Desktop/TTF/SourceSerif4-Regular.ttf": "source_serif_4_regular.ttf",
    "source-serif-4.005_Desktop/TTF/SourceSerif4-It.ttf": "source_serif_4_italic.ttf",
    "source-serif-4.005_Desktop/TTF/SourceSerif4-Bold.ttf": "source_serif_4_bold.ttf",
}

with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
    lic_content = z.read("source-serif-4.005_Desktop/LICENSE.md")
    (lic_dir / "LICENSE-Source-Serif-4.md").write_bytes(lic_content)
    for zip_path, dest_name in serif_map.items():
        raw_data = z.read(zip_path)
        temp_raw = f"/tmp/{dest_name}.raw.ttf"
        with open(temp_raw, "wb") as f:
            f.write(raw_data)
        dest_path = font_dir / dest_name
        cmd = [
            "pyftsubset",
            temp_raw,
            f"--output-file={dest_path}",
            f"--unicodes={unicodes_latin}",
            "--layout-features=*",
            "--glyph-names",
            "--symbol-cmap",
            "--legacy-cmap",
            "--notdef-glyph",
            "--notdef-outline",
            "--recommended-glyphs",
        ]
        subprocess.check_call(cmd)
        orig_sz = len(raw_data)
        sub_sz = dest_path.stat().st_size
        print(f"  {dest_name}: {orig_sz} -> {sub_sz} bytes ({sub_sz/1024:.1f} KB)")
        os.remove(temp_raw)

total_font_bytes = sum(f.stat().st_size for f in font_dir.glob("*.ttf"))
print(f"\nTotal font size in app/src/main/res/font: {total_font_bytes} bytes ({total_font_bytes / (1024*1024):.2f} MB)")
