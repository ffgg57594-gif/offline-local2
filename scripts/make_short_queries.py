#!/usr/bin/env python3
"""Stage K5d: Generate eval/short_queries.jsonl.

Contains:
- 60 in-scope queries of 1 to 4 words (chosen from book section headings /
  key medical terms in chunks with target chunk IDs and pages).
- 30 short out-of-scope queries (other specialties, non-medical, passing mentions).
"""
import json
import os

OUT_PATH = os.path.join("eval", "short_queries.jsonl")

IN_SCOPE = [
    (1, "Maternal physiologic changes", 16, 11),
    (2, "Skeletal changes pregnancy", 31, 15),
    (3, "Double marker test", 61, 23),
    (4, "Amniocentesis timing risks", 69, 25),
    (5, "McDonald cerclage operation", 90, 33),
    (6, "Gestational trophoblastic neoplasia", 122, 44),
    (7, "Antepartum hemorrhage causes", 127, 46),
    (8, "Placenta previa expectant", 150, 53),
    (9, "Management of eclampsia", 180, 60),
    (10, "Magnesium sulfate toxicity", 181, 61),
    (11, "Acute cystitis pregnancy", 215, 70),
    (12, "Anticonvulsant fetal effects", 225, 72),
    (13, "Rh isoimmunization incidence", 236, 76),
    (14, "Fetal skull anatomy", 258, 84),
    (15, "Delivery of shoulders", 288, 93),
    (16, "Non stress test", 309, 100),
    (17, "Fetal heart decelerations", 318, 102),
    (18, "Vaginal breech delivery", 343, 110),
    (19, "Shoulder presentation lie", 358, 115),
    (20, "Prolonged second stage", 388, 124),
    (21, "Cephalopelvic disproportion outlet", 405, 130),
    (22, "Obstructed labor rupture", 411, 133),
    (23, "Placenta accreta spectrum", 442, 143),
    (24, "Manual placenta removal", 446, 144),
    (25, "Tocolytic therapy PTL", 471, 150),
    (26, "Fetal macrosomia risks", 500, 159),
    (27, "Preconception counseling obesity", 502, 159),
    (28, "Puerperal wound infection", 539, 170),
    (29, "Perineal laceration repair", 558, 176),
    (30, "Cesarean lower segment", 571, 181),
    (31, "Antenatal history investigations", 576, 184),
    (32, "Pelvic ureter anatomy", 601, 195),
    (33, "Primary amenorrhea causes", 617, 199),
    (34, "Precocious puberty investigations", 647, 210),
    (35, "Menopause breast changes", 654, 212),
    (36, "Asherman syndrome pathogenesis", 677, 218),
    (37, "Basal body temperature", 699, 224),
    (38, "Ovarian drilling PCOS", 711, 228),
    (39, "Submucous uterine leiomyoma", 739, 237),
    (40, "Laparoscopy dye test", 744, 239),
    (41, "IUD insertion timing", 780, 249),
    (42, "IUD pelvic infection", 787, 252),
    (43, "Emergency contraception barrier", 814, 259),
    (44, "Bacterial vaginosis etiology", 822, 261),
    (45, "Acute endocervicitis treatment", 838, 266),
    (46, "Gonococcal endocervicitis symptoms", 872, 276),
    (47, "Syphilis secondary stage", 890, 281),
    (48, "Cysto urethrocele prolapse", 896, 284),
    (49, "Kelly plication sutures", 923, 293),
    (50, "Vesicovaginal fistula exclusion", 935, 296),
    (51, "Uterine fibroid calcification", 968, 307),
    (52, "Fibroid pressure symptoms", 973, 308),
    (53, "Functional ovarian cysts", 1009, 319),
    (54, "Follicular cyst regression", 1011, 319),
    (55, "Cervical intraepithelial neoplasia", 1047, 330),
    (56, "Pap smear screening", 1054, 333),
    (57, "Ovarian neoplasms classification", 1079, 340),
    (58, "Ovarian swelling investigations", 1104, 347),
    (59, "Granulosa cell tumors", 1119, 351),
    (60, "Ovarian cancer IVP", 1134, 356),
]

OUT_OF_SCOPE = [
    # Other specialties (12)
    (61, "Psoriasis vulgaris symptoms", "other_specialty"),
    (62, "Adult cataract surgery", "other_specialty"),
    (63, "Dental caries fluoride", "other_specialty"),
    (64, "Schizophrenia diagnostic criteria", "other_specialty"),
    (65, "Brain glioblastoma treatment", "other_specialty"),
    (66, "Cirrhosis hepatic encephalopathy", "other_specialty"),
    (67, "Chronic gastritis pylori", "other_specialty"),
    (68, "Bronchial pneumonia consolidation", "other_specialty"),
    (69, "Rheumatoid arthritis synovitis", "other_specialty"),
    (70, "Alzheimer disease dementia", "other_specialty"),
    (71, "Parkinson disease tremor", "other_specialty"),
    (72, "Myocardial infarction ECG", "other_specialty"),
    # Non-medical (10)
    (73, "Quantum computing qubits", "non_medical"),
    (74, "French revolution dates", "non_medical"),
    (75, "Chocolate cake recipe", "non_medical"),
    (76, "Basic guitar chords", "non_medical"),
    (77, "Python decorators tutorial", "non_medical"),
    (78, "Tokyo train schedule", "non_medical"),
    (79, "Capital of Australia", "non_medical"),
    (80, "Solar panel installation", "non_medical"),
    (81, "Stock market indices", "non_medical"),
    (82, "Mount Everest height", "non_medical"),
    # Ob/Gyn passing mentions / non-book out of scope (8)
    (83, "Canine veterinary dystocia", "passing_mention"),
    (84, "Drosophila embryogenesis genetics", "passing_mention"),
    (85, "Cosmetic labiaplasty cost", "passing_mention"),
    (86, "Bovine artificial insemination", "passing_mention"),
    (87, "Transgender gender reassignment", "passing_mention"),
    (88, "Neonatal cardiac surgery", "passing_mention"),
    (89, "Fetal pig dissection", "passing_mention"),
    (90, "Maternal healthcare economics", "passing_mention"),
]


def main():
    rows = []
    for qid, q, target_chunk_id, page in IN_SCOPE:
        words = q.split()
        assert 1 <= len(words) <= 4, f"Query '{q}' word count {len(words)} not in 1..4"
        rows.append({
            "id": qid,
            "q": q,
            "target_chunk_id": target_chunk_id,
            "page": page,
            "in_scope": True,
            "word_count": len(words),
        })

    for qid, q, cat in OUT_OF_SCOPE:
        words = q.split()
        assert 1 <= len(words) <= 4, f"Query '{q}' word count {len(words)} not in 1..4"
        rows.append({
            "id": qid,
            "q": q,
            "target_chunk_id": None,
            "page": None,
            "in_scope": False,
            "category": cat,
            "word_count": len(words),
        })

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Wrote {len(rows)} queries to {OUT_PATH} (60 in-scope, 30 out-of-scope)")


if __name__ == "__main__":
    main()
