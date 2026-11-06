#!/usr/bin/env python3
"""Generate app/src/test/resources/tokenizer_reference.json.

Creates ~424 reference cases:
  - 120 golden questions from eval/golden_v3.draft.jsonl (prefix "query: ")
  - 150 chunks from books_knowledge.db (seed 7, prefix "passage: ", including at least 10 > 384 tokens)
  - 130 hand-made edge cases (Arabic, mixed, accented, Greek, digits, apostrophes, dashes, etc.)
  - 24 embedder reference cases from assets/embedder_reference.json
Each entry has: id, category, input, ids, expected_attention_length.
"""
import json
import os
import random
import sqlite3
import sys

from tokenizers import Tokenizer

TOKENIZER_PATH = os.path.join("app", "src", "main", "assets", "models", "embedder", "tokenizer.json")
DB_PATH = os.path.join("app", "src", "main", "assets", "books_knowledge.db")
GOLDEN_PATH = os.path.join("eval", "golden_v3.draft.jsonl")
EMB_REF_PATH = os.path.join("app", "src", "main", "assets", "embedder_reference.json")
OUT_PATH = os.path.join("app", "src", "test", "resources", "tokenizer_reference.json")

MAX_LENGTH = 384


def main():
    if not os.path.exists(TOKENIZER_PATH):
        print(f"ERROR: {TOKENIZER_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    tok = Tokenizer.from_file(TOKENIZER_PATH)

    def encode_case(text: str):
        enc = tok.encode(text)
        ids = enc.ids[:MAX_LENGTH]
        return ids, len(ids)

    cases = []
    case_id = 1

    # 1. 120 Golden questions
    if not os.path.exists(GOLDEN_PATH):
        print(f"ERROR: {GOLDEN_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden_lines = [line.strip() for line in f if line.strip()]

    for line in golden_lines:
        obj = json.loads(line)
        q = obj["q"]
        inp = "query: " + q
        ids, att_len = encode_case(inp)
        cases.append({
            "id": case_id,
            "category": "golden_query",
            "input": inp,
            "ids": ids,
            "expected_attention_length": att_len
        })
        case_id += 1

    # 2. 150 Chunk texts (seed 7, prefix "passage: ", at least 10 longer than 384 tokens)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, text FROM chunks ORDER BY id")
    all_chunks = cur.fetchall()
    conn.close()

    rng = random.Random(7)
    # Sample 135 normal chunks
    sampled_135 = rng.sample(all_chunks, 135)
    for cid, text in sampled_135:
        inp = "passage: " + text
        ids, att_len = encode_case(inp)
        cases.append({
            "id": case_id,
            "category": "chunk_passage",
            "input": inp,
            "ids": ids,
            "expected_attention_length": att_len
        })
        case_id += 1

    # 15 long chunks (combining 3 consecutive chunks to guarantee > 384 tokens)
    long_count = 0
    for i in range(15):
        indices = [i * 30, i * 30 + 1, i * 30 + 2]
        combined_text = " ".join(all_chunks[idx % len(all_chunks)][1] for idx in indices)
        inp = "passage: " + combined_text
        ids, att_len = encode_case(inp)
        if len(tok.encode(inp).ids) > 384:
            long_count += 1
        cases.append({
            "id": case_id,
            "category": "chunk_passage_long",
            "input": inp,
            "ids": ids,
            "expected_attention_length": att_len
        })
        case_id += 1

    assert long_count >= 10, f"Expected at least 10 long chunks, got {long_count}"

    # 3. 130 Hand-made edge cases
    raw_edge_cases = [
        # Arabic only
        ("arabic_medical", "التهاب الزائدة الدودية الحاد وعلاجه الجراحي"),
        ("arabic_medical", "تسمم الحمل وارتفاع ضغط الدم الشديد أثناء الثلث الثالث"),
        ("arabic_medical", "النزيف المهبلي بعد الولادة الطبيعية وطرق التدخل"),
        ("arabic_medical", "تشخيص سكر الحمل باستخدام اختبار تحمل الجلوكوز"),
        ("arabic_medical", "أعراض فقر الدم المنجلي وطرق نقل الدم الوقائية"),
        ("arabic_medical", "الفشل الكلوي الحاد والمزمن والغسيل البريتوني"),
        ("arabic_medical", "الذبحة الصدرية غير المستقرة واحتشاء عضلة القلب"),
        ("arabic_medical", "الربو القصبي الحاد والعلاج بموسعات الشعب الهوائية"),
        ("arabic_medical", "التهاب الكبد الوبائي الفيروسي ب وس"),
        ("arabic_medical", "مرض السكري من النوع الأول وحموضة الدم الكيتونية"),
        ("arabic_medical", "قصور الغدة الدرقية وارتفاع الهرمون المنشط"),
        ("arabic_medical", "اليرقان الوليدي وارتفاع نسبة البيليروبين غير المقترن"),
        ("arabic_medical", "التهاب السحايا الجرثومي عند الأطفال والرضع"),
        ("arabic_medical", "الصدمة الإنتانية وانخفاض ضغط الدم المعند"),
        ("arabic_medical", "تضخم البروستاتا الحميد واحتباس البول الحاد"),
        ("arabic_medical", "القرحة الهضمية المنثقبة واستقصاء البطن الحاد"),
        ("arabic_medical", "الانسداد الرئوي الحاد وتجلط الأوردة العميقة"),
        ("arabic_medical", "التهاب البنكرياس الحاد وارتفاع إنزيم الأميلاز"),
        ("arabic_medical", "كسر عنق الفخذ عند كبار السن وهشاشة العظام"),
        ("arabic_medical", "السكتة الدماغية الإقفارية والعلاج بمذيب الخثرة"),
        
        # Mixed Arabic / English
        ("mixed_ar_en", "فحص CBC و HbA1c لمتابعة مرضى diabetes mellitus"),
        ("mixed_ar_en", "علاج postpartum hemorrhage باستخدام oxytocin و misoprostol"),
        ("mixed_ar_en", "بروتوكول magnesium sulfate للوقاية من eclampsia"),
        ("mixed_ar_en", "تشخيص deep vein thrombosis بواسطة Doppler ultrasound"),
        ("mixed_ar_en", "إعطاء IV fluids لمرضى septic shock"),
        ("mixed_ar_en", "إجراء emergency Cesarean section عند fetal distress"),
        ("mixed_ar_en", "تأثير beta-blockers على ejection fraction في heart failure"),
        ("mixed_ar_en", "استخدام ACE inhibitors لمرضى diabetic nephropathy"),
        ("mixed_ar_en", "علاج community-acquired pneumonia بواسطة azithromycin"),
        ("mixed_ar_en", "قياس Glasgow Coma Scale (GCS) لمرضى head trauma"),
        ("mixed_ar_en", "تثبيط H. pylori باستخدام triple therapy: amoxicillin + clarithromycin + PPI"),
        ("mixed_ar_en", "نتائج CT scan أظهرت acute appendicitis with perforation"),
        ("mixed_ar_en", "مستويات troponin I مرتفعة في acute myocardial infarction"),
        ("mixed_ar_en", "إجراء arterial blood gas (ABG) لتقييم metabolic acidosis"),
        ("mixed_ar_en", "متابعة viral load و CD4 count لمرضى HIV infection"),

        # Accented Latin
        ("accented_latin", "café au lait spots and neurofibromatosis"),
        ("accented_latin", "Ménière's disease and vertigo symptoms"),
        ("accented_latin", "Guillain-Barré syndrome after acute infection"),
        ("accented_latin", "Sjögren syndrome with dry eyes and dry mouth"),
        ("accented_latin", "Hashimoto thyroiditis and Graves ophthalmopathy"),
        ("accented_latin", "Chédiak-Higashi syndrome with recurrent pyogenic infections"),
        ("accented_latin", "Sézary syndrome and cutaneous T-cell lymphoma"),
        ("accented_latin", "Creutzfeldt-Jakob disease and rapid prion dementia"),
        ("accented_latin", "Peutz-Jeghers syndrome with gastrointestinal polyposis"),
        ("accented_latin", "François dyscephaly and Hallermann-Streiff syndrome"),
        ("accented_latin", "Löffler syndrome and pulmonary eosinophilia"),
        ("accented_latin", "Kallmann syndrome with anosmia and hypogonadism"),
        ("accented_latin", "Köbner phenomenon in psoriasis vulgaris"),
        ("accented_latin", "Rendu-Osler-Weber hereditary hemorrhagic telangiectasia"),
        ("accented_latin", "Bruton agammaglobulinemia and X-linked inheritance"),

        # Greek letters
        ("greek_letters", "α-thalassemia major and Hb Barts hydrops fetalis"),
        ("greek_letters", "β-thalassemia minor trait and microcytic anemia"),
        ("greek_letters", "α1-antitrypsin deficiency and pulmonary emphysema"),
        ("greek_letters", "β-blocker therapy with metoprolol succinate"),
        ("greek_letters", "γ-aminobutyric acid (GABA) receptor agonists"),
        ("greek_letters", "δ-cells of pancreas secreting somatostatin"),
        ("greek_letters", "ε-chain of fetal hemoglobin HbF"),
        ("greek_letters", "ζ-potential of colloidal suspensions"),
        ("greek_letters", "TNF-α and IL-1β in chronic systemic inflammation"),
        ("greek_letters", "TGF-β signaling in tissue fibrosis"),
        ("greek_letters", "IFN-γ release assay for latent tuberculosis"),
        ("greek_letters", "COX-1 and COX-2 inhibition by NSAIDs"),
        ("greek_letters", "CD4+ Th17 producing IL-17α and IL-22"),
        ("greek_letters", "μ-opioid receptor stimulation by morphine"),
        ("greek_letters", "κ-light chains in multiple myeloma"),

        # Digits and phrases like "5-year-old"
        ("digits_and_phrases", "A 5-year-old child presents with high fever and cough"),
        ("digits_and_phrases", "BP 120/80 mmHg, pulse 72 bpm, temp 37.0 C"),
        ("digits_and_phrases", "Hb 8.5 g/dL, WBC 15,400 /mm3, Platelets 250,000 /uL"),
        ("digits_and_phrases", "Serum creatinine 2.4 mg/dL, BUN 45 mg/dL, eGFR 28 mL/min/1.73m2"),
        ("digits_and_phrases", "Sodium 138 mEq/L, Potassium 4.2 mEq/L, Chloride 101 mEq/L"),
        ("digits_and_phrases", "Glucose 280 mg/dL, HbA1c 9.8%, ketones positive 3+"),
        ("digits_and_phrases", "Patient aged 65-year-old male with 40-pack-year smoking history"),
        ("digits_and_phrases", "Dose: 500 mg PO BID x 7 days or 1 g IV TID"),
        ("digits_and_phrases", "PaO2 65 mmHg, PaCO2 48 mmHg, pH 7.31, HCO3 24 mEq/L"),
        ("digits_and_phrases", "Infant weight 3.250 kg, head circumference 35 cm, APGAR 9/10"),

        # Straight and curly apostrophes
        ("apostrophes", "patient's chart indicates Crohn's disease"),
        ("apostrophes", "patient’s chart indicates Crohn’s disease"),
        ("apostrophes", "it's known that Alzheimer's and Parkinson's co-occur"),
        ("apostrophes", "it’s known that Alzheimer’s and Parkinson’s co-occur"),
        ("apostrophes", "doctor's orders vs doctors' consensus"),
        ("apostrophes", "doctor’s orders vs doctors’ consensus"),
        ("apostrophes", "'primary' outcome vs ‘secondary’ outcome"),
        ("apostrophes", "‘warning: patient’s vitals unstable’"),

        # Hyphens and en/em dashes
        ("hyphens_and_dashes", "pre-eclampsia and post-partum hemorrhage"),
        ("hyphens_and_dashes", "blood pressure 120–140 mmHg is borderline"),
        ("hyphens_and_dashes", "symptoms—fever, cough, and dyspnea—worsened"),
        ("hyphens_and_dashes", "short-term vs long-term treatment outcomes"),
        ("hyphens_and_dashes", "dose range 5–10 mg once daily"),
        ("hyphens_and_dashes", "the patient—despite warnings—continued smoking"),
        ("hyphens_and_dashes", "insulin-dependent diabetes mellitus (IDDM)"),
        ("hyphens_and_dashes", "non–small-cell lung cancer (NSCLC)"),

        # Uppercase
        ("uppercase", "ACUTE RESPIRATORY DISTRESS SYNDROME (ARDS) IN ICU"),
        ("uppercase", "NORMAL SALINE 0.9% SODIUM CHLORIDE 1000 ML IV INFUSION"),
        ("uppercase", "DO NOT RESUSCITATE (DNR) ORDER CONFIRMED BY FAMILY"),
        ("uppercase", "HELLP SYNDROME: HEMOLYSIS, ELEVATED LIVER ENZYMES, LOW PLATELETS"),
        ("uppercase", "EMERGENCY PROTOCOL ACTIVATED: CODE BLUE ROOM 304"),

        # Tabs, newlines, multiple spaces
        ("whitespace_special", "Line 1\tTab separated\tValues"),
        ("whitespace_special", "Line 1\nLine 2\nLine 3 with medical notes"),
        ("whitespace_special", "Paragraph with\r\nCRLF line breaks\r\nand tabs\t\tend"),
        ("whitespace_special", "Excessive     spaces     between     words     here"),
        ("whitespace_special", "\t\tLeading tabs and trailing tabs\t\t"),
        ("whitespace_special", "\n\nLeading and trailing newlines\n\n"),
        ("whitespace_special", "Mix of \t tabs, \n newlines,   and multiple spaces."),

        # Emoji and zero-width characters
        ("emoji_and_special", "Patient feels happy 😊 after successful recovery 👍"),
        ("emoji_and_special", "Emergency warning ⚠️ high cardiac risk 🚨"),
        ("emoji_and_special", "Heart rate ❤️ 80 bpm, temperature 🌡️ 37 C"),
        ("emoji_and_special", "Medicine prescribed 💊💉 for pain relief"),
        ("emoji_and_special", "Zero\u200bwidth\u200bspace\u200btest"),
        ("emoji_and_special", "Zero\ufeffwidth\ufeffno\ufeffbreak\ufeffspace"),
        ("emoji_and_special", "BOM prefix \ufeffPatient medical summary"),

        # Empty, spaces only, single character
        ("empty_and_spaces", ""),
        ("empty_and_spaces", " "),
        ("empty_and_spaces", "   "),
        ("empty_and_spaces", "\t\n\r"),
        ("empty_and_spaces", "a"),
        ("empty_and_spaces", "و"),
        ("empty_and_spaces", "."),
        ("empty_and_spaces", "1"),

        # Long repeated word
        ("long_repeated_word", "supercalifragilisticexpialidocious" * 15),
        ("long_repeated_word", "pneumonoultramicroscopicsilicovolcanoconiosis " * 10),
        ("long_repeated_word", "pseudopseudohypoparathyroidism " * 12),
        ("long_repeated_word", "مستشفى " * 60),
    ]

    for cat, text in raw_edge_cases:
        ids, att_len = encode_case(text)
        cases.append({
            "id": case_id,
            "category": cat,
            "input": text,
            "ids": ids,
            "expected_attention_length": att_len
        })
        case_id += 1

    # 4. 24 Embedder reference cases
    if os.path.exists(EMB_REF_PATH):
        with open(EMB_REF_PATH, "r", encoding="utf-8") as f:
            emb_ref = json.load(f)
        for e in emb_ref.get("entries", []):
            pref = "passage: " if e["kind"] == "passage" else "query: "
            text = pref + e["input"]
            ids, att_len = encode_case(text)
            cases.append({
                "id": case_id,
                "category": "embedder_reference_" + e["kind"],
                "input": text,
                "ids": ids,
                "expected_attention_length": att_len
            })
            case_id += 1

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "total_cases": len(cases),
            "max_length": MAX_LENGTH,
            "cases": cases
        }, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {len(cases)} cases into {OUT_PATH}")


if __name__ == "__main__":
    main()
