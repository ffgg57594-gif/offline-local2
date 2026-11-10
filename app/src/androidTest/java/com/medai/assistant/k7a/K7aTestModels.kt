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
 * `klosax/tinyllamas-stories-gguf` mirrors karpathy/tinyllamas (MIT);
 * the file is downloaded through the production [ModelManager] +
 * DownloadManager path and its pinned sha256 is verified before use.
 * The test model is never bundled inside the APK.
 */
object K7aTestModels {

    const val TINY_URL =
        "https://huggingface.co/klosax/tinyllamas-stories-gguf/resolve/main/" +
            "tinyllamas-stories-260k-f32.gguf"
    const val TINY_SHA256 =
        "c14806920629b6c217445c69d7ac61bd0e4047289f8ab824c3f0b4f827a5d1cb"
    const val TINY_SIZE_BYTES = 1_182_656L

    @Volatile
    private var managerRef: ModelManager? = null

    @Volatile
    private var fileRef: File? = null

    fun catalogEntry(): CatalogModel = CatalogModel(
        id = "tinyllamas-stories-260k-f32",
        displayName = "TinyLlama stories 260K (test)",
        fileName = "tinyllamas-stories-260k-f32.gguf",
        repo = "klosax/tinyllamas-stories-gguf",
        url = TINY_URL,
        sizeBytes = TINY_SIZE_BYTES,
        sha256 = TINY_SHA256,
        license = "mit",
        licenseLine = "license: mit (source: karpathy/tinyllamas)",
        licenseUrl = "https://huggingface.co/karpathy/tinyllamas",
        ramEstimateMb = 64,
        ramEstimateCalc = "test model: 1.1 MB f32 base model, ctx 256",
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
