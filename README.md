# Offline Strict Medical Textbooks Chat

Native Android app (Kotlin + Jetpack Compose, Material 3) that answers ONLY from medical PDF textbooks baked in at build time. Extractive-first: no hallucination by construction.

## Phone-only workflow
1. Upload PDFs to `app/src/main/assets/books/` via GitHub web UI.
2. Put `eval/golden_questions.jsonl` (optional) for the retrieval gate.
3. Run the `Build APK` workflow from the Actions tab.
4. Download the APK from Releases and install.

## Limits
- GitHub web upload: 25 MB per file.
- Git: 100 MB per file (use Git LFS for larger).
- APK must be < 1.8 GB.

## Model
The LLM (GGUF) is not in the repo/APK. Use the in-app Model Manager to download (default Qwen2.5-1.5B-Instruct Q4_K_M) or import a .gguf.

## العربية
تطبيق أندرويد أصلي (Kotlin + Jetpack Compose) يجيب فقط من الكتب الطبية PDF المدمجة at build time. راجع workflow لبناء APK.
