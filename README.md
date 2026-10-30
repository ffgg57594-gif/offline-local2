# المساعد الطبي / MedAI Assistant

Empty-but-correct Android skeleton. Builds a signed APK on GitHub Actions. No features yet.

## Where to put PDFs
Place PDF textbooks in `app/src/main/assets/books/`. They are NOT packaged in the APK (ignored via ignoreAssetsPattern).

## Build from a phone
1. Upload PDFs to `app/src/main/assets/books/` via GitHub web UI.
2. Open the Actions tab → "Build APK" → Run workflow.
3. Download the APK from the Releases page (tagged build-<run_number>).
4. Install on device (enable unknown sources).

## GitHub upload limits
- Web UI: 25 MB per file.
- Git: 100 MB per file.
- Use Git LFS for larger files.
