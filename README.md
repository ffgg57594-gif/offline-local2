# المساعد الطبي / MedAI Assistant

Android app that answers only from medical PDF textbooks baked in at build time. Stage 1 green: signed APK builds on GitHub Actions.

## Where to put PDFs
Place PDF textbooks in `app/src/main/assets/books/`. They are NOT packaged in the APK (ignored via `ignoreAssetsPattern = "!books"`).

## How the book database is built
CI runs `scripts/build_knowledge_db.py` (Python, PyMuPDF) before the Gradle build: extracts text per page, cleans headers/footers, de-hyphenates, chunks into 100–180 word windows (never crossing a page boundary), skips TOC/index/short pages and drops low-quality chunks, writes `app/src/main/assets/books_knowledge.db` (SQLite + FTS5) — gitignored, never committed. The APK contains `assets/books_knowledge.db` but no `.pdf`.

Optional manual skip: `scripts/skip_pages.json` maps book name to page numbers to skip, e.g. `{"425_OBG_clean_single_pages": [1, 2]}`. Create it with `{}` and edit as needed.

تجاوز صفحات يدوياً: ملف `scripts/skip_pages.json` يربط اسم الكتاب بأرقام الصفحات للتجاوز، مثلاً `{"425_OBG_clean_single_pages": [1, 2]}`. أنشئه بـ `{}` وعدل حسب الحاجة.

## Build from a phone
1. Upload PDFs to `app/src/main/assets/books/` via GitHub web UI.
2. Open the Actions tab → "Build APK" → Run workflow.
3. Download the APK from the Releases page (tagged build-<run_number>).
4. Install on device (enable unknown sources).

## GitHub upload limits
- Web UI: 25 MB per file.
- Git: 100 MB per file.
- Use Git LFS for larger files.

كيف تُبنى قاعدة بيانات الكتب (Arabic)
يُشغل CI سكريبت `scripts/build_knowledge_db.py` (بايثون، PyMuPDF) قبل البناء:
- يستخرج نص كل صفحة من كل ملف `*.pdf` في `app/src/main/assets/books/`.
- ينظف العناوين المتكررة، ويصلح الكلمات المنقوطة، ويقسّم إلى مقاطع 100–180 كلمة بدون تجاوز حدود الصفحة.
- يكتب `app/src/main/assets/books_knowledge.db` (SQLite + FTS5) — هذا الملف غيرمراقب في git ولا يتم تضمينه في git.
- يحتوي APK على `assets/books_knowledge.db` ولا يحتوي على أي `.pdf`.

## How embeddings are built (Stage 3)
CI downloads the quantized ONNX model `Xenova/multilingual-e5-small` from Hugging Face Hub into `app/src/main/assets/models/embedder/`, then runs `scripts/build_embeddings.py` to embed every chunk from `books_knowledge.db` into `assets/embeddings.bin` (float32 matrix [N, 384], L2-normalized, mean-pooled). Reference vectors are written to `assets/embedder_reference.json` for Kotlin parity tests. All generated assets are gitignored and never committed.

كيف تُبنى التضمينات (Arabic)
يُحصل CI على نموذج Xenova/multilingual-e5-small المضغوط بصيغة ONNX من منصة Hugging Face إلى `app/src/main/assets/models/embedder/`، ثم يشغل `scripts/build_embeddings.py` لتضمين كل مقطع من `books_knowledge.db` في `assets/embeddings.bin` (مصفوفة float32 [N, 384]، مبرمعة L2، متوسطة التجميع). تُكتب مراجع المتجهات إلى `assets/embedder_reference.json` لاختبارات المطابقة بلغة Kotlin. كل الأصول المولدة غير مراقبة في git ولا تُكرمَّت.

## Retrieval evaluation audit and fusion re-tuning (Stage 3.6b)
CI runs `scripts/evaluate_audit.py` for a per-question audit with explicit hit definitions:
  - **Answer-term hit**: chunk contains ALL terms of at least one answer_terms group.
  - **Page hit**: chunk page number is in expected_pages.
It flags "weak label" questions (>15 matching chunks) and reports recall under both
definitions for all questions and strong-label questions only.

CI runs `scripts/keyword_builder.py` (v2 builder: stopword-only + short non-content
list of max 40 words; document-frequency removal removed) and compares keyword
variants v1-v4. CI runs `scripts/fusion_tuning.py` for weighted RRF re-tuning
(k in {10, 60}, w_kw in {0, 0.25, 0.5, 1.0}, 5-fold CV, answer-term metric).
w_kw > 0 is chosen only if mean hit@3 beats w_kw=0 by >= 0.03; otherwise w_kw=0.
The result is written to `assets/fusion_config.json` (gitignored, never committed).

### Hit definitions (explicit)
A chunk is a HIT if it contains ALL terms of at least one answer_terms group,
checked with the same normalization and tokenizer as the FTS5 index.
A result list is a hit at k if any of its top-k chunks is a HIT.
Page-based hit (expected_pages) is reported separately.

### Keyword builder v2
- Normalization: lowercase, hyphen unification, spelling variants (normalize_map.json)
- Stopword removal: 150+ English words including question words
- Non-content word list (max 40): patient, patients, case, cases, type, types,
  following, used, include, including, ... (printed in full in CI log)
- Document-frequency based removal is REMOVED — in a single-specialty book,
  words like "pregnancy", "hemorrhage", "uterine" are content words.
- Variants: v1 (stopwords + DF removal), v2 (stopword-only unigrams + bm25),
  v3 (v2 + adjacent-word phrases), v4 (v3 + column weights).

## How the book database is built (schema v2)
CI runs `scripts/build_knowledge_db.py` with schema_version=2: adds a
`search_text` column (normalized text) indexed by FTS5 with
`tokenize='porter unicode61 remove_diacritics 2'`. `chunks.text` stays verbatim.
Chunk ids and texts are unchanged from Stage 3; `embeddings_meta.json` includes
`chunk_texts_sha256` and the build fails if the DB and matrix disagree.

## Embeddings integrity
`scripts/build_embeddings.py` computes sha256 over all chunk texts and stores it
in `embeddings_meta.json`. The CI verifies both hashes match.

## Generated assets (gitignored, never committed)
- `app/src/main/assets/books_knowledge.db` (SQLite + FTS5)
- `app/src/main/assets/embeddings.bin` (float32 matrix [N, 384])
- `app/src/main/assets/embeddings_meta.json`
- `app/src/main/assets/embedder_reference.json` (24 reference vectors)
- `app/src/main/assets/models/embedder/model_quantized.onnx`
- `app/src/main/assets/models/embedder/tokenizer.json`
- `app/src/main/assets/models/embedder/config.json`
- `app/src/main/assets/normalize_map.json` (37 spelling variants kept)
- `app/src/main/assets/fusion_config.json` (weighted RRF config)
- `app/src/main/assets/medical_aliases.json` (150+ OB/GYN terms, not used in Stage 3.6b)

## Build from a phone
1. Upload PDFs to `app/src/main/assets/books/` via GitHub web UI.
2. Open the Actions tab → "Build APK" → Run workflow.
3. Download the APK from the Releases page (tagged build-<run_number>).
4. Install on device (enable unknown sources).

## GitHub upload limits
- Web UI: 25 MB per file.
- Git: 100 MB per file.
- Use Git LFS for larger files.

كيف تُبنى قاعدة البيانات وتُجرى التقييم (Arabic Stage 3.6b)
يشغل CI `scripts/evaluate_audit.py` لمراجعة كل سؤال بتعريفات hit واضحة:
  - **hit بالنص الإجابي**: المقتطف يحتوي على جميع مصطلحات مجموعة answer_terms واحدة على الأقل.
  - **hit بالصفحة**: رقم صفحة المقتطف موجود في expected_pages.
يُسئل "العلامة الضعيفة" (>15 مقتطف مطابق) ويُبلغ عن الاستدعاء تحت كلا التعريفين
لكل الأسئلة والأسئلة ذات العلامة القوية فقط.

يشغل CI `scripts/keyword_builder.py` (باني الاستعلام v2: توقف فقط + قائمة غير محتوى قصيرة
بحد أقصى 40 كلمة؛ إزالة التكرار حسب تكرار الوثيقة حُذفت). يقارن CI بين متغيرات
الكلمات المفتاحية v1-v4. يشغل CI `scripts/fusion_tuning.py\) لإعادة ضبط الدمج المرجحي
(k في {10, 60}, w_kw في {0, 0.25, 0.5, 1.0}, تحقق متقاطع 5 أضعاف، مقياس مصطلح الإجابة).
يُختار w_kw > 0 فقط إذا تجاوز متوسط hit@3 قيمة w_kw=0 بمقدار >= 0.03؛ وإلا يُبقي w_kw=0.
تُكتب النتيجة إلى `assets/fusion_config.json` (غير مراقب في git ولا يُكرمَّت).

## تعريفات hit (واضحة)
المقتطف هو HIT إذا كان يحتوي على جميع مصطلحات مجموعة answer_terms واحدة على الأقل،
يتم التحقق من خلال نفس التطبيع والمُرمّز لمؤشر FTS5.
قائمة النتائج هي hit عند k إذا كان أي من أفضل k مقتطفات هو HIT.
يتم الإبلاغ عن hit بناءً على الصفحة (expected_pages) بشكل منفصل.

## باني الاستعلام v2
- التطبيع: أحرف صغيرة، توحيد الفواصل،renuants إملائية (normalize_map.json)
- إزالة كلمات التوقف: 150+ كلمةإنجليزية بما في ذلك كلمات الأسئلة
- قائمة الكلمات غير المحتوى (بحد أقصى 40): patient, patients, case, cases, type, types,
  following, used, include, including, ... (تُطبع بالكامل في سجل CI)
- الإزالة بناءً على تكرار الوثيقة حُذفت — في كتاب تخصص واحد، كلمات مثل "pregnancy",
  "hemorrhage", "uterine" هي كلمات محتوى.
- المتغيرات: v1 (توقف + إزالة DF)، v2 (توقف فقط + أحرف فردية + bm25)،
  v3 (v2 + عبارات الكلمات المتجاورة)، v4 (v3 + أوزان الأعمدة).

## Signal measurements: eval/gate_signals.csv (Stage 3.7b)
- Measures refusal-gate signals (s1-s5) for 60 in-scope (golden_v3) and 60 balanced out-of-scope questions (golden_oos_v3: 24 other-specialty medical Class A, 24 unaddressed Ob/Gyn passing mentions Class B, and 12 distinct non-medical Class N). Measurement only: no thresholds chosen, not bundled in APK.
- Ambiguous questions answered by the book (hypertension, diabetes, heart/liver disease in pregnancy) are moved to eval/ambiguous.jsonl.
- قياس إشارات بوابة الرفض (s1-s5) لـ 60 سؤالاً ضمن النطاق و60 سؤالاً خارج النطاق متوازنة (golden_oos_v3: 24 تخصص طبي آخر فئة A، 24 سؤال نساء وتوليد غير مجاب فئة B، و12 غير طبي متنوع فئة N). قياس فقط: بدون اختيار عتبات ولا يُشحن مع APK.
- الأسئلة الملتبسة المجابة في الكتاب (الضغط، السكري، أمراض القلب والكبد أثناء الحمل) نُقلت إلى eval/ambiguous.jsonl.

## Refusal Gate Frozen Presets (Stage 3.7c)
- Refusal gate parameters fitted from real signals: balanced (t1=0.84, t3=0.5714, k=0) and strict (t1=0.8525, t3=0.5714, k=0).
- Label fixes applied in eval/label_fixes.json (B 26, 29, 48 answered by book); hyphen compound tokenization unified bidirectionally.
- Bundled in assets/gate_config.json and assets/gate_reference.json (120 questions decisions); no Kotlin or retrieval changes.
- معايير بوابة الرفض المجمدة من الإشارات الحقيقية: الإعداد المتوازن (t1=0.84, t3=0.5714, k=0) والصارم (t1=0.8525, t3=0.5714, k=0).
- تطبيق تصحيحات التصنيف في eval/label_fixes.json ومعالجة الكلمات المركبة ذات الوصلات ثنائية الاتجاه، وتضمين ملفات التهيئة والمرجع في الحزمة.
