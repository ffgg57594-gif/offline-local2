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
