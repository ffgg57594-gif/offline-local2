# HANDOFF — Offline Medical Assistant (offline-local2)

## Project Overview

- **App:** Offline Android medical reference assistant (Kotlin, Jetpack Compose, ONNX Runtime Mobile, SQLite FTS5) that answers English Obstetrics & Gynaecology medical questions **strictly** from one embedded textbook: `app/src/main/assets/books/425_OBG_clean_single_pages.pdf` (375 pages, 1,185 chunks).
- **Core Security & Privacy Boundary:** All retrieval (tokenization, vector embedding, similarity search, gate decisions) still runs 100% locally on-device. Since K7a the app requests exactly two permissions: `INTERNET` + `POST_NOTIFICATIONS` — the network is used **only** by the in-app model downloader (`app/src/main/java/com/medai/assistant/llm/download/`) to fetch the GGUF chat model the user explicitly chooses in Settings → الموديل. `scripts/check_network_usage.py` fails CI when any code outside that package references `java.net`/`okhttp`/`HttpURLConnection`/`openConnection`/`WebView`/`DownloadManager`, the network security config forbids cleartext, and "Verify APK contents" asserts the APK permission set is exactly `INTERNET` + `POST_NOTIFICATIONS`.
- **Target Architecture:** `arm64-v8a` only for release APK; R8 full minification enabled. Debug and test APKs support both `arm64-v8a` and `x86_64` (for API 34 emulator testing).
- **Repository:** `https://github.com/ffgg57594-gif/offline-local2` — branch `main`.
- **CI / Build Harness:** GitHub Actions workflow (`Build APK` in `.github/workflows/build_apk.yml`). The project is developed and maintained via an automated phone-friendly harness; all releases are built, tested on an emulator, signed, and published automatically on GitHub Actions.

---

## Current Status: Completed & Verified (Build 177 / Run #177)

As of commit `533ce0448ba7caa732bf2664b35453e3dcb9ad11` (Tag `build-177`), all stages from K1 through Stage UI-B are **100% GREEN and verified**:

### 1. Data & Pre-processing Pipeline (Python on CI)
- **PDF Extraction & Chunking:** `scripts/build_knowledge_db.py` extracts 375 pages into 1,185 clean chunks (100–180 words, no page-boundary crossing) stored in SQLite FTS5 database `books_knowledge.db` (schema v2 with normalized `search_text`).
- **On-Device Model & Embeddings:** Quantized ONNX model `Xenova/multilingual-e5-small` embeds all 1,185 chunks into `assets/embeddings.bin` (float32 matrix [1185, 384], L2-normalized). SHA-256 integrity hash is checked on every build.
- **Refusal Gate Calibration:** Calibrated refusal gate parameters fitted from real cosine signals:
  - **Balanced:** $t_1 = 0.8375$, $t_3 = 0.571429$, $k = 0$, margin $0.01$.
  - **Strict:** $t_1 = 0.8525$, $t_3 = 0.571429$, $k = 0$, margin $0.01$.
  - Presets frozen in `assets/gate_config.json`.

### 2. Android & Kotlin Core Engine (Stages K1 – K4d)
- **K1 (Repository & Asset Installer):** Efficient SQLite FTS5 extraction and querying on initial launch.
- **K2 / K2b (Tokenizer):** Pure Kotlin tokenizer using compiled binary trie `tokenizer.bin` (416/416 parity test cases vs Hugging Face Python reference).
- **K3 / K3c (Embedder & Search Parity):** `OnnxEmbedder` running via ONNX Runtime Android + `DenseSearch`. CI generates `eval/retrieval_top5.csv` and verifies parity with zero tolerance for stale references.
- **K4 / K4c (Kotlin Gate & Parity):** Calibrated refusal gate in pure Kotlin matching Python decisions.
- **K4d (On-Device Parity on Emulator):** API 34 headless emulator boot (`reactivecircus/android-emulator-runner@v2`) running instrumented tests:
  - `DeviceEmbedderParityTest`: 24 reference vectors verified on-device.
  - `DeviceTokenizerParityTest`: Tokenizer parity on-device.
  - `DeviceFts5Test`: Full SQLite FTS5 query parity.
  - `DeviceGateStemsParityTest`: Exact stem matching on Android ICU.
  - `DevicePipelineParityTest`: End-to-end question verification.

### 3. Real Device Pipeline & UI Test Suite (Stages K5a – K5c)
- **K5b Real Pipeline (120 Questions):** All 120 golden evaluation questions evaluated through the real on-device engine on the API 34 emulator:
  - Balanced preset: **120 / 120** match Python reference (100%).
  - Strict preset: **119 / 120** match Python reference (99.2%, required $\ge 117/120$).
  - Mean $| \Delta s_1 |$: $0.000238$.
- **Per-Stage Latency Benchmark:**
  - Tokenize: p50 = 0 ms, p95 = 5 ms.
  - Embed: p50 = 55 ms, p95 = 79 ms.
  - Search: p50 = 7 ms, p95 = 17 ms.
  - Gate Signals: p50 = 5 ms, p95 = 29 ms.
  - Gate Decision: p50 = 0 ms, p95 = 0 ms.
  - **Total Search Pipeline:** p50 = 72 ms, p95 = 90 ms (warmup: 113 ms).
  - Cold Start: 128,749 ms (process creation to ready), Model Load: 268 ms.
- **K5c Compose UI Testing:** 12 required UI cases + 7 extra state tests (total 19 UI tests, 0 failures).
- **14 Unique Verified UI Screenshots:** All 14 UI screenshots captured and verified with unique SHA-256 hashes (total 11.35 MB, strictly under 25 MB limit).

### 4. Design System & Real Screen Migration (Stages UI-A & UI-B)
- **Design System ("ورق وحبر" Paper & Ink):**
  - **Palette:** Deep Teal `#0F5C5C` (primary), Terracotta Alert `#BA3D2A` (refusal/error), Warm Parchment `#F7F4EE` (light surface), Warm Charcoal `#1B1D1E` (dark surface), Amber Highlighter `#F8E4B3` (light) / `#4E3E18` (dark).
  - **Typography:** `Source Serif 4` (OFL) for medical textbook passages, `IBM Plex Sans Arabic` (OFL) for UI and system controls.
  - **Components:** Margin rail cards with bookmark tab ("ص 261"), rank chip, explicit bidi citation line (`\u2068` / `\u2069`), pinned-header/footer passage sheet, floating input bar with IME padding, canvas-drawn empty state illustration (no bitmap assets).
  - **Contrast:** 100% WCAG AA compliance across all 36 element pairs in both Light and Dark themes.
  - **No Gallery in Release:** `DesignGallery` and debug composables are isolated to the `debug` source set. The release APK contains **zero** gallery classes or strings (verified via `scripts/verify_release_no_gallery.py`).
- **Real Screen Migration (Stage UI-B):** `MainActivity.kt`, `AskScreen.kt`, and `SettingsSheet.kt` fully migrated to `MedAiDesignTheme`.

### 5. Stage K5d (Real-Phone Insets, Real Keyboard Screenshots, Short-Query Study)
- **Part A (UI Fixes):**
  - **Window Insets & Keyboard:** Added `android:windowSoftInputMode="adjustResize"` in `AndroidManifest.xml` preventing Android WindowManager from panning window decor into status bar. In `AskScreen.kt`, set `Scaffold(contentWindowInsets = WindowInsets(0, 0, 0, 0))` and on `InputBar` applied `Modifier.windowInsetsPadding(WindowInsets.navigationBars.union(WindowInsets.ime))`, eliminating the floating gap above the soft keyboard. TopBar remains pinned at the top. On submission/results, the list scrolls to show the first card fully and keyboard is dismissed.
  - **Header Deduplication:** Subtitle set to `"يجيب من الكتاب المدمج فقط"` while retaining the separate `"بدون إنترنت"` badge.
  - **Card Citation vs Page:** Card citation chip displays only `"المصدر: " + bookTitle` (page number omitted from this chip), while the prominent page chip (`"ص 261"`) is kept. Full citation string (`PassageText.citation(bookName, page)`) is preserved in `PassageSheet` (`sheet_citation`) and copy action.
- **Part B (Real-Keyboard Full Display Screenshots):**
  - UiAutomator captures full SurfaceFlinger display (status bar, navigation bar, and IME window):
    - `01_empty_keyboard_open.png`: Empty state with real IME keyboard open.
    - `02_results_keyboard_closed.png`: Results state with keyboard closed.
    - `03_long_question_keyboard_open.png`: 3-line long medical question with real IME open.
  - Artifact `ui-screenshots-v3` uploaded and validated by `scripts/check_screenshots_v3.py` (fails on duplicates or missing files).
- **Part C (Short-Query Study — Measurement Only):**
  - Dataset: `eval/short_queries.jsonl` containing 60 in-scope queries (1–4 words each, derived from book section headings / key terms with target chunk IDs and pages) and 30 short out-of-scope queries (other specialties, non-medical, passing mentions).
  - Retrieval evaluated across Dense, BM25 (FTS5), and RRF fusion ($k \in \{10, 60\}$, $w_{\text{kw}} \in \{0.0, 0.25, 0.5, 1.0\}$) on target-only and same-page metrics.
  - Gate evaluation: Balanced preset accepts **58/60** (96.7%) and rejects **30/30** OOS (100.0%); Strict preset accepts **54/60** (90.0%) and rejects **30/30** OOS (100.0%).
  - Full distributions of $s_1, s_3, s_4$ and rejected query listings generated in `build/reports/k5d/short_queries_report.md`.

---

### 5. Latest Release Evidence (Build 177)
- **CI Run:** [GitHub Actions Run #177](https://github.com/ffgg57594-gif/offline-local2/actions/runs/42622133886)
- **Release Tag:** [`build-177`](https://github.com/ffgg57594-gif/offline-local2/releases/tag/build-177)
- **Commit:** `533ce0448ba7caa732bf2664b35453e3dcb9ad11`
- **Release APK:** `app-release-unsigned.apk` (151,647,344 bytes / 144.62 MiB).
- **Delta vs `build-156`:** +1,628,185 bytes (+1.55 MiB) due to bundled OFL font families and design assets.
- **Instrumented Tests:** 69 / 69 PASSED on API 34 emulator.

---

## 14 Official UI Screenshots (SHA-256 Hashes)

| # | Filename | Size (bytes) | SHA-256 Hash | State Description |
|---|---|---:|---|---|
| 01 | `01_empty_light.png` | 189,758 | `8f87ab2d613506d488d918d3788587d0be10edae42bb01d7ec32723f276dfb90` | Empty state (Light), canvas book illustration, 4 example chips |
| 02 | `02_empty_dark.png` | 180,012 | `a7c5b94f10100ce2f9f86d8448cf8e308a015010aecc8566e08676c0d4566f69` | Empty state (Dark), warm charcoal background |
| 03 | `03_results_light_keyboard_closed.png` | 364,653 | `a7a23d892d7aea2ce1808c2a78a216e47e6b67b46c05052430ea9356941a4d91` | Results state (Light), 3 passage cards, page bookmark tab |
| 04 | `04_results_dark_keyboard_closed.png` | 341,968 | `e0335a1ce07ce4c8932bdc532141d2450cc852db5f91104e5ab8fe6ba15982c2` | Results state (Dark), dark amber marker highlights |
| 05 | `05_results_font13_dark.png` | 326,691 | `c0ea9375f0fb3880a0da4e48a6860f9bf26d3b8d9a3d31dd2786b7c71a5f610e` | Results state at 1.3x font scale (Dark), zero text clipping |
| 06 | `06_sheet_top_light.png` | 414,903 | `a40d8f1452e91c840ae6032f25679966157213633a125d7d55141416a5747d79` | Full passage sheet top (Light), pinned header & position indicator |
| 07 | `07_sheet_bottom_light.png` | 311,465 | `da8b39f5278f9d7087022a1bb1832209e2453037aaade13a19915e35d9908363` | Full passage sheet bottom (Light), pinned footer navigation buttons |
| 08 | `08_sheet_top_font13_light.png` | 421,095 | `359940ebf0be5116d3798ac8c4cf79342613f7419b7540af492dff84bff7886c` | Full passage sheet top at 1.3x font scale (Light) |
| 09 | `09_sheet_bottom_font13_light.png` | 317,537 | `897c3935a07d32ec1253ab6b05dadb593b714eb78cd30b16ae2dcd413c9e8685` | Full passage sheet bottom at 1.3x font scale, touch target $\ge 48\text{dp}$ |
| 10 | `10_refusal_collapsed_light.png` | 123,369 | `7697eb086339189b414c488ed1603f41bbe663682671d258e364093b980b703d` | Refusal card collapsed (Light), terracotta alert badge |
| 11 | `11_refusal_expanded_light.png` | 239,549 | `c5b39f1fd46b2580b127a5632f2cac9575704fb5a2080e969529eeafdc8d8a8f` | Refusal card expanded showing nearest results |
| 12 | `12_loading_searching_light.png` | 102,983 | `b963d7d0f0382e567733454ae511b683f7d57cd212df33e1723fbb738c7e1d9a` | Searching progress card with cancel button |
| 13 | `13_settings_strict_light.png` | 182,911 | `7ea107b5c0ac285649a3d817398117ecb9e093b91b0dd05032d8daac1cce51cc` | Settings sheet with strict preset selected |
| 14 | `14_long_english_passage_light.png` | 400,115 | `276bbdd2e7ff4713910405a9dab64fdadf2ea4fd92f2d33a0adf44fd8916a0b0` | Long English passage preserving LTR flow inside RTL shell |

---

## Key Facts & Invariants to Maintain

1. **Retrieval is Dense Only:** All passages come from `DenseSearch` against `assets/embeddings.bin`. Exact chunk top-1 accuracy is ~43%, top-3 accuracy is ~78%. The application always presents the top 3 passages with citation to book title and page number.
2. **Deterministic Parity Across Runners:** `embeddings.bin` SHA-256 can vary slightly between CPU architectures (e.g. AVX-512 vs AVX2); always generate and test reference parity within the same CI workflow run.
3. **Restricted INTERNET Permission (K7a):** The app requests exactly `android.permission.INTERNET` + `android.permission.POST_NOTIFICATIONS`. The network is used **only** inside `app/src/main/java/com/medai/assistant/llm/download/` to download the user-selected GGUF model. `scripts/check_network_usage.py` fails CI on any network-API reference outside that package; any other network feature request must be rejected.
4. **arm64-v8a Only for Release:** The release APK ABI is strictly restricted to `arm64-v8a` (`ndk { abiFilters "arm64-v8a" }`).
5. **Release APK Has No Gallery Code:** Keep all gallery composables in `app/src/debug/`. The release task automatically runs `verify_release_no_gallery.py`.
6. **Local Development Container (Proot):** The local container runs in proot on an Android phone. Never start background Gradle daemons or run unconstrained builds locally. Rely on GitHub Actions for full compilation, emulator testing, and APK signing.
7. **Git Discipline:**
   - Never force-push (`git push --force`) or rewrite history.
   - Always run `git fetch` and `git log origin/main -3` before every push.
   - First line of every model reply to the user must be in Arabic.
   - Never invent, estimate, or retype numerical values; extract them verbatim from CI logs or scripts.

---

## Future Roadmap (Post-UI-B)

- **History & Bookmarking:** Room-based persistent query history and saved passages.
- **Offline OCR Scanner:** Camera-based physical book page scanner using Google ML Kit Text Recognition on-device.
- **On-Device LLM Synthesis ("Explain"):** Optional on-device generative summary (e.g. Gemma-2B / MediaPipe LLM Inference) when hardware permits, guarded by the existing calibrated retrieval and refusal gate.
