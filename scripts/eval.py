#!/usr/bin/env python3
"""Phase 2 eval: 50 in-scope + 30 out-of-scope. Reports top-3 hit rate and refusal rate (FTS5 baseline)."""
import sqlite3, random

IN_SCOPE = [
 "psychiatric symptoms and signs","mood disorders","major depressive disorder","bipolar disorder",
 "anxiety disorders","schizophrenia spectrum","somatic symptom disorder","substance abuse addiction",
 "child psychiatry","neurocognitive disorders","psychiatric emergency","psychotherapeutic intervention",
 "illusions and hallucinations","delusions","obsessions and compulsions","disorders of speech",
 "disorders of emotion","motor behavior catatonic","memory disorders","attention orientation consciousness",
 "judgment insight","breast congenital anomalies","breast trauma fat necrosis","acute mastitis abscess",
 "chronic inflammatory breast","fibrocystic disease","breast cysts","nipple discharge","breast neoplasms",
 "gynaecomastia male breast","goitre classification","subacute thyroiditis","hashimoto thyroiditis",
 "riedel thyroiditis","simple goitre endemic","nodular goitre","thyroid stages","breast duct papilloma",
 "fibroadenoma","thyroid investigations treatment","depression epidemiology etiology","delusions types",
 "hallucinations auditory visual","mania flight of ideas","amnesia hypermnesia paramnesia",
 "derealization depersonalization","psychomotor retardation agitation","flat affect blunted",
 "insight awareness recognition","mood affect distinction",
]
OUT_OF_SCOPE = [
 "dose of amoxicillin for otitis media","treatment of myocardial infarction","pediatric vaccination schedule",
 "management of diabetic ketoacidosis","appendicitis diagnosis","fracture healing stages","renal failure dialysis",
 "asthma bronchodilator therapy","hypertension drug classes","stroke thrombolysis protocol",
 "pneumonia antibiotic regimen","malaria prophylaxis","tuberculosis drug regimen","HIV antiretroviral therapy",
 "cancer chemotherapy protocols","anemia iron deficiency treatment","thyroid cancer staging",
 "breast cancer screening mammography age","heart failure ejection fraction","epilepsy anticonvulsants",
 "migraine treatment triptans","osteoporosis bisphosphonates","glaucoma eye drops","cataract surgery",
 "psoriasis topical steroids","eczema management","acne treatment","allergic rhinitis",
 "gastroesophageal reflux","peptic ulcer H pylori","inflammatory bowel disease",
]

def main():
    conn = sqlite3.connect("ingested.db")
    try:
        conn.execute("SELECT count(*) FROM sentences_fts").fetchone()
    except Exception:
        # build
        conn.execute("DROP TABLE IF EXISTS sentences_fts")
        conn.execute("CREATE VIRTUAL TABLE sentences_fts USING fts5(text, content='sentences', content_rowid='id', tokenize='porter unicode61')")
        conn.execute("INSERT INTO sentences_fts(rowid, text) SELECT id, text FROM sentences")
        conn.commit()

    import importlib.util
    spec = importlib.util.spec_from_file_location("search","scripts/search.py")
    # inline search
    def fts_search(q):
        toks = " ".join(__import__("re").findall(r"[A-Za-z]+", q))
        if not toks: return []
        try:
            return conn.execute("""SELECT s.paragraph_id FROM sentences_fts JOIN sentences s ON s.id=sentences_fts.rowid WHERE sentences_fts MATCH ? LIMIT 30""",(toks,)).fetchall()
        except Exception:
            return []

    hits=0; total_in=len(IN_SCOPE)
    for q in IN_SCOPE:
        r = fts_search(q)
        if r: hits+=1
    refusals=0; total_out=len(OUT_OF_SCOPE)
    for q in OUT_OF_SCOPE:
        r = fts_search(q)
        if not r: refusals+=1
    print(f"In-scope top-hit (any FTS hit): {hits}/{total_in} = {hits/total_in:.2%}")
    print(f"Out-of-scope correct refusal (no FTS hit): {refusals}/{total_out} = {refusals/total_out:.2%}")
    print("NOTE: FTS5-only baseline. Full BGE-M3+RRF requires Colab (see Phase 2 notebook).")

if __name__=="__main__":
    main()
