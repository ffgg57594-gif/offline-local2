#!/usr/bin/env python3
"""Text normalization for the retrieval pipeline.

Provides:
  - normalize_text(text): lowercase, unify hyphens, apply spelling-variant map, NFKC,
    strip zero-width chars, collapse whitespace.
  - load_variant_map(path): load normalize_map.json.
  - build_variant_map(db_path, full_map_path, out_path): filter variant map to only
    pairs whose source OR target appears in the corpus; write out_path.

Run as a script to generate assets/normalize_map.json from books_knowledge.db.
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata

DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
FULL_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.full.json")
OUT_MAP_PATH = os.path.join("app", "src", "main", "assets", "normalize_map.json")

ZERO_WIDTH = "\u200b\u200c\u200d\ufeff"

# Full spelling-variant map (British -> American and other common variants).
# Only variants whose source OR target appear in the corpus are kept.
FULL_VARIANTS = {
    # British spelling -> American spelling
    "labour": "labor",
    "haemorrhage": "hemorrhage",
    "anaemia": "anemia",
    "oedema": "edema",
    "foetal": "fetal",
    "foetus": "fetus",
    "pre-eclampsia": "preeclampsia",
    "pre eclampsia": "preeclampsia",
    "oestrogen": "estrogen",
    "caesarean": "cesarean",
    "paediatric": "pediatric",
    "diarrhoea": "diarrhea",
    "foetus": "fetus",
    "foetal": "fetal",
    "gynaecology": "gynecology",
    "gynaecological": "gynecological",
    "haemoglobin": "hemoglobin",
    "haematology": "hematology",
    "haemorrhoids": "hemorrhoids",
    "manoeuvre": "maneuver",
    "oesophagus": "esophagus",
    "oestriol": "estriol",
    "oestradiol": "estradiol",
    "paediatrics": "pediatrics",
    "paediatrician": "pediatrician",
    "foetoscope": "fetoscope",
    "foetal": "fetal",
    "foetoscopy": "fetoscopy",
    "anaesthesia": "anesthesia",
    "anaesthetist": "anesthetist",
    "anaesthetize": "anesthetize",
    "anaesthetized": "anesthetized",
    "anaesthetizing": "anesthetizing",
    "anaesthetic": "anesthetic",
    "anaesthetics": "anesthetics",
    "anaesthesiology": "anesthesiology",
    "analogue": "analog",
    "catalogue": "catalog",
    "dialogue": "dialog",
    "favour": "favor",
    "favourite": "favorite",
    "flavour": "flavor",
    "honour": "honor",
    "humour": "humor",
    "neighbour": "neighbor",
    "paralyse": "paralyze",
    "paralysed": "paralyzed",
    "paralysing": "paralyzing",
    "recognise": "recognize",
    "recognised": "recognized",
    "organisation": "organization",
    "organise": "organize",
    "realise": "realize",
    "specialise": "specialize",
    "summarise": "summarize",
    "tumour": "tumor",
    "tumours": "tumors",
    "valour": "valor",
    "vigour": "vigor",
    "armour": "armor",
    "ardour": "ardor",
    "clamour": "clamor",
    "colour": "color",
    "demeanour": "demeanor",
    "endeavour": "endeavor",
    "harbour": "harbor",
    "labour": "labor",
    "odour": "odor",
    "rigour": "rigor",
    "saviour": "savior",
    "splendour": "splendor",
    "tumour": "tumor",
    "clamour": "clamor",
    "dysmenorrhoea": "dysmenorrhea",
    "menorrhoea": "menorrhea",
    "metrorrhagia": "metrorrhagia",
    "polymenorrhoea": "polymenorrhea",
    "oligomenorrhoea": "oligomenorrhea",
    "hyperemesis": "hyperemesis",
    "haematuria": "hematuria",
    "haemoptysis": "hemoptysis",
    "haemothorax": "hemothorax",
    "haemosiderosis": "hemosiderosis",
    "haemolysis": "hemolysis",
    "haemolytic": "hemolytic",
    "haemophilia": "hemophilia",
    "haemorrhoid": "hemorrhoid",
    "haemodynamic": "hemodynamic",
    "haemoglobinuria": "hemoglobinuria",
    "haemoglobinopathy": "hemoglobinopathy",
}


def normalize_text(text, variant_map=None):
    """Normalize a text string for indexing/searching.

    Steps:
      1. NFKC Unicode normalization.
      2. Strip zero-width characters.
      3. Lowercase.
      4. Unify hyphens and dashes to ASCII hyphen.
      5. Apply spelling-variant map (longest match first).
      6. Collapse whitespace.
    """
    text = unicodedata.normalize("NFKC", text)
    for ch in ZERO_WIDTH:
        text = text.replace(ch, "")
    text = text.lower()
    # Unify hyphen-like characters to ASCII hyphen.
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", text)
    if variant_map:
        # Sort variants by source length descending for longest-match-first.
        sorted_variants = sorted(variant_map.items(), key=lambda kv: -len(kv[0]))
        for src, dst in sorted_variants:
            text = re.sub(r"\b" + re.escape(src) + r"\b", dst, text)
    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_variant_map(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_variant_map(db_path, full_map_path, out_path):
    """Filter FULL_VARIANTS to only pairs whose source OR target appears in corpus."""
    if not os.path.exists(db_path):
        print(f"ERROR: {db_path} not found. Run build_knowledge_db.py first.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute("SELECT text FROM chunks").fetchall()
    corpus = " ".join(r[0] for r in rows).lower()
    conn.close()

    kept = {}
    for src, dst in FULL_VARIANTS.items():
        # Check if source or target appears as a whole word in the corpus.
        if re.search(r"\b" + re.escape(src) + r"\b", corpus) or re.search(r"\b" + re.escape(dst) + r"\b", corpus):
            kept[src] = dst

    print(f"Kept {len(kept)} of {len(FULL_VARIANTS)} spelling variants.")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(kept, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {out_path}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        build_variant_map(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        # Default: build from books_knowledge.db into assets/normalize_map.json
        if os.path.exists(OUT_MAP_PATH):
            os.remove(OUT_MAP_PATH)
        build_variant_map(DB_PATH, FULL_MAP_PATH, OUT_MAP_PATH)
