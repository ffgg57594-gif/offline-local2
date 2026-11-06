# HANDOFF — Offline Medical Assistant (offline-local2)

## Project

- Offline Android app (Kotlin, Jetpack Compose) that answers English medical questions **only** from one obstetrics and gynaecology book:
  `app/src/main/assets/books/425_OBG_clean_single_pages.pdf` (375 pages,
  sha256 `356d8194...`).
- The APK is built and signed by GitHub Actions (workflow **"Build APK"**) because the
  developer works only from a phone.
- Repo: https://github.com/ffgg57594-gif/offline-local2 — branch `main`.

## State

Done (CI was green at the last trusted report):

- **Python pipeline on CI:** PDF -> 1185 chunks -> SQLite (`books_knowledge.db`) ->
  `embeddings.bin` (multilingual-e5-small quantized ONNX, 1185x384 float32) -> eval
  files, refusal-gate signals and presets
  (`assets/gate_config.json`: balanced t1 0.8375, t3 0.571429, k 0; strict t1 0.8525;
  margin 0.01).
- **Kotlin K1:** asset installer + chunk repository.
- **K2/K2b:** tokenizer (`tokenizer.bin`, 416/416 parity cases vs Python).
- **K3:** `OnnxEmbedder` + `DenseSearch` + debug screen with timing.
- **K3b:** parity reports written by the tests.

Not built yet:

- **K3c** (current task — see below)
- **K4:** refusal gate in Kotlin.
- **K5:** chat UI (top-3 passages with page citation), history/settings,
  attachments/OCR, model manager and LLM "Explain".

## Facts to keep

- Retrieval is **dense only**. Honest accuracy against the original source chunk:
  exact chunk top-1 **43%**, top-3 about **78%**. The app must show the top 3
  passages with book and page.
- Numbers depend on the runner CPU type: `embeddings.bin` sha256 is `6d0ad0de...` on
  one type and `5d647d89...` on another; s1 differs by up to about 0.005 and 4 of 60
  in-scope top-1 chunks flip. **Never compare files from different jobs without
  checking the `embeddings.bin` sha256.**
- Out-of-scope class B ids **26, 29, 48** are answered by the book
  (`eval/label_fixes.json`).
- No `INTERNET` permission yet. R8 on. `arm64-v8a` only.
- A previous agent could not install PyMuPDF or a C compiler in its local environment,
  so the Python pipeline ran only in GitHub Actions. Verify on the current machine.

## Rules

- Never force-push or rewrite history.
- Run `git fetch` and `git log origin/main -3` **before every push**, and stop if there
  are commits you did not make.
- Never touch `app/src/main/assets/books/`.
- Replies in Arabic or English only (first line Arabic).
- Every number must come from a CI log, an artifact file, or the output of a script
  actually run: never retype, estimate or invent numbers or tables.
- Never print tool calls as text.
- Never say a stage is complete while CI is red.
- Paste requested tables in full.

## Current task (K3c)

Regenerate `eval/retrieval_top5.csv` in the **same CI job** after building
`embeddings.bin`; store the `embeddings.bin` sha256, CPU model and onnxruntime version
beside it; the Kotlin test must fail with **"stale reference"** on a mismatch; then
report top-1 identical and `|delta s1|` max/p95/mean computed from
`build/reports/parity/retrieval_parity.csv`.
