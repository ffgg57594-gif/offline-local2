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
- يكتب `app/src/main/assets/books_knowledge.db` (SQLite + FTS5) — هذا الملف غيرمراقب في git ولا يُ커밋.
- يحتوي APK على `assets/books_knowledge.db` ولا يحتوي على أي `.pdf`.

## How embeddings are built (Stage 3)
CI downloads the quantized ONNX model `Xenova/multilingual-e5-small` from Hugging Face Hub into `app/src/main/assets/models/embedder/`, then runs `scripts/build_embeddings.py` to embed every chunk from `books_knowledge.db` into `assets/embeddings.bin` (float32 matrix [N, 384], L2-normalized, mean-pooled). Reference vectors are written to `assets/embedder_reference.json` for Kotlin parity tests. All generated assets are gitignored and never committed.

كيف تُبنى التضمينات (Arabic)
يُحصل CI على نموذج Xenova/multilingual-e5-small المضغوط بصيغة ONNX من منصة Hugging Face إلى `app/src/main/assets/models/embedder/`، ثم يشغل `scripts/build_embeddings.py` لتضمين كل مقطع من `books_knowledge.db` في `assets/embeddings.bin` (مصفوفة float32 [N, 384]، مبرمعة L2، متوسطة التجميع). تُكتب مراجع المتجهات إلى `assets/embedder_reference.json` لاختبارات المطابقة بلغة Kotlin. كل الأصول المولدة غير مراقبة في git ولا تُكرمَّت.

## Retrieval evaluation and threshold calibration (Stage 3.5)
CI runs `scripts/evaluate_dense_vs_keyword.py` for a dense-vs-keyword-vs-fusion sanity table, `scripts/evaluate_golden.py` for golden-set recall/MRR, and `scripts/calibrate_gate.py` to recommend a strict similarity gate (dense score, dense+keyword, or fusion only) from the draft golden set in `eval/golden_questions.draft.jsonl`. The calibrated gate is written to `assets/config_calibrated.json` (gitignored, never committed).

Arabic query expansion uses `app/src/main/assets/medical_aliases.json` (about 150 OB/GYN terms with Arabic keys and English values). When an Arabic query contains an alias key, the English terms are appended for both dense and keyword search. Alias verification: each English term must have FTS5 hit count > 0 in the built database; otherwise it is dropped.

## كيف تُجرى التقييم والمعايرة (Arabic Stage 3.5)
يشغل CI `scripts/evaluate_dense_vs_keyword.py` لجدول المقارنة بين البحث الكثيف والكلمات المفتاحية والدمج، و`scripts/evaluate_golden.py` لاستدعاء واسترجاع مجموعة الأسئلة الذهبية، و`scripts/calibrate_gate.py` للمعايرة وتحديد بوابة التشابه الصارمة (النقاط الكثيفة فقط، أو الكثيفة + 키워د، أو الدمج فقط) من مجموعة الأسئلة الذهبية المسودة في `eval/golden_questions.draft.jsonl`. تُكتب البوابة المعايرة إلى `assets/config_calibrated.json` (غير مراقب في git ولا يُكرمَّت).

يتم توسيع الاستعلام العربي باستخدام `app/src/main/assets/medical_aliases.json` (حوالي 150 مصطلح توليد وإنجاب مع مفاتيح عربية وقيم إنجليزية). عندما يحتوي الاستعلام العربي على مفتاح تتبع، تُضاف المصطلحات الإنجليزية لكل من البحث الكثيف وبحث الكلمات المفتاحية. تُتحقق من المستعارات: يجب أن يكون لكل مصطلح إنجليزي عدد نقاط FTS5 أكبر من 0 في قاعدة البيانات المبنية؛ وإلا يُسقط.
