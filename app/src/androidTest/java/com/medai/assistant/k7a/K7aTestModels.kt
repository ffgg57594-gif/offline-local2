package com.medai.assistant.k7a

import android.content.Context
import android.os.Environment
import com.medai.assistant.llm.CatalogModel
import com.medai.assistant.llm.ModelManager
import com.medai.assistant.llm.ModelState
import com.medai.assistant.llm.ModelStorage
import com.medai.assistant.llm.SharedPrefsStore
import com.medai.assistant.llm.download.AndroidModelDownloader
import java.io.File

/**
 * K7a: the few-MB public test GGUF used by the on-device tests.
 *
 * `ggml-org/test-model-stories260K` is llama.cpp's own CI re-export of
 * karpathy/tinyllamas stories260K (MIT) in GGUF v3 — the pinned submodule
 * (b12236) rejects GGUF v1 files ("GGUFv1 is no longer supported"), so the
 * original klosax mirror of the v1 file cannot be loaded. The file is
 * downloaded through the production [ModelManager] + DownloadManager path
 * and its pinned sha256 is verified before use. The test model is never
 * bundled inside the APK.
 */
object K7aTestModels {

    const val TINY_URL =
        "https://huggingface.co/ggml-org/test-model-stories260K/resolve/main/" +
            "stories260K-f32.gguf"
    const val TINY_SHA256 =
        "270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d"
    const val TINY_SIZE_BYTES = 1_185_376L

    @Volatile
    private var managerRef: ModelManager? = null

    @Volatile
    private var fileRef: File? = null

    fun catalogEntry(): CatalogModel = CatalogModel(
        id = "stories260k-f32",
        displayName = "TinyLlama stories 260K (test)",
        fileName = "stories260K-f32.gguf",
        repo = "ggml-org/test-model-stories260K",
        url = TINY_URL,
        sizeBytes = TINY_SIZE_BYTES,
        sha256 = TINY_SHA256,
        license = "mit",
        licenseLine = "license: mit (source: karpathy/tinyllamas, re-exported by ggml-org)",
        licenseUrl = "https://huggingface.co/karpathy/tinyllamas",
        ramEstimateMb = 64,
        ramEstimateCalc = "test model: 1.13 MB f32 stories260K (292.8K params), ctx 256",
        isDefault = true
    )

    /**
     * Downloads (once per process) the tiny model through the exact
     * production path: DownloadManager enqueue -> poll -> size + sha256
     * verify -> rename into filesDir/models.
     */
    fun ensureDownloaded(context: Context, timeoutMs: Long = 300_000): File {
        fileRef?.let { if (it.isFile && it.length() == TINY_SIZE_BYTES) return it }
        synchronized(this) {
            fileRef?.let { if (it.isFile && it.length() == TINY_SIZE_BYTES) return it }
            val app = context.applicationContext
            val model = catalogEntry()
            val manager = managerRef ?: ModelManager(
                catalog = listOf(model),
                storage = ModelStorage(
                    filesDir = app.filesDir,
                    downloadDir = app.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
                ),
                downloader = AndroidModelDownloader(app),
                store = SharedPrefsStore(app, "k7a_test_models"),
                pollMs = 500L
            ).also { managerRef = it }
            // Re-attaches to a download that survived a process restart.
            manager.resumeOnStart()
            manager.refresh()
            manager.installedFileFor(model)?.let {
                fileRef = it
                return it
            }
            if (manager.stateOf(model.id) !is ModelState.Downloading) {
                manager.download(model)
            }
            val deadline = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < deadline) {
                when (val state = manager.stateOf(model.id)) {
                    is ModelState.Ready -> {
                        val file = manager.installedFileFor(model)
                            ?: error("model reported Ready but the file is missing")
                        fileRef = file
                        return file
                    }
                    is ModelState.Error -> throw AssertionError(
                        "tiny model download failed: ${state.message}"
                    )
                    else -> Thread.sleep(500)
                }
            }
            throw AssertionError("tiny model download timed out after ${timeoutMs}ms")
        }
    }
}
