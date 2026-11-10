package com.medai.assistant.llm

import com.medai.assistant.llm.download.DownloadStatus
import com.medai.assistant.llm.download.ModelDownloader
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File
import java.io.InputStream

/** Tiny persistence abstraction so the state machine is JVM-testable. */
interface KeyValueStore {
    fun getString(key: String): String?
    fun putString(key: String, value: String)
    fun remove(key: String)
    fun clear()
}

/**
 * K7a: download / verify / install lifecycle for the GGUF chat models.
 *
 * - Every byte is downloaded by Android's DownloadManager inside the
 *   download package (the only code allowed to touch network APIs).
 * - Before a file is trusted its size and sha256 must match the catalog;
 *   a mismatch deletes the file and shows "الملف غير مطابق للمتوقع".
 * - Verified files are renamed into filesDir/models/<fileName>.
 * - State survives rotation (StateFlow) and process death (DownloadManager
 *   ids are persisted and re-queried on start; installed files are scanned).
 * - SAF import accepts only files whose sha256 equals a catalog entry.
 */
class ModelManager(
    catalog: List<CatalogModel>,
    private val storage: ModelStorage,
    private val downloader: ModelDownloader,
    private val store: KeyValueStore,
    private val spaceProvider: () -> Long = { storage.usableBytes() },
    private val pollMs: Long = 400L
) {

    private val catalog: List<CatalogModel> = catalog
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutex = Mutex()

    private val _states = MutableStateFlow(
        catalog.associate { it.id to ModelState.NotInstalled as ModelState }
    )
    val states: StateFlow<Map<String, ModelState>> = _states.asStateFlow()

    private val pollingJobs = mutableMapOf<String, Job>()

    init {
        require(catalog.isNotEmpty()) { "model catalog must not be empty" }
    }

    fun models(): List<CatalogModel> = catalog

    fun modelById(id: String): CatalogModel? = catalog.firstOrNull { it.id == id }

    fun stateOf(id: String): ModelState =
        _states.value[id] ?: ModelState.NotInstalled

    fun installedFileFor(model: CatalogModel): File? = storage.installedFileFor(model)

    fun anyInstalledFile(): File? = storage.listInstalled().firstOrNull()

    /** Re-attaches persisted downloads and scans installed files. */
    fun resumeOnStart() {
        scope.launch {
            mutex.withLock {
                refreshLocked()
                for (model in catalog) {
                    val id = store.getString(downloadKey(model.id)) ?: continue
                    val downloadId = id.toLongOrNull() ?: continue
                    when (val status = downloader.query(downloadId, storage.downloadTempFile(model))) {
                        is DownloadStatus.Successful -> finalizeLocked(model, status.file)
                        is DownloadStatus.Failed -> cleanupLocked(model, downloadId)
                        is DownloadStatus.Unknown -> cleanupLocked(model, downloadId)
                        else -> {
                            setStateLocked(model, ModelState.Downloading(model.id, 0L, model.sizeBytes))
                            startPollingLocked(model, downloadId)
                        }
                    }
                }
            }
        }
    }

    /** Marks models whose verified file is present as Ready. */
    fun refresh() {
        scope.launch {
            mutex.withLock { refreshLocked() }
        }
    }

    private fun refreshLocked() {
        for (model in catalog) {
            val file = storage.installedFileFor(model) ?: continue
            setStateLocked(
                model,
                ModelState.Ready(model.id, file.name, file.length())
            )
        }
    }

    /** Starts a download after the 1.3x free-space check. */
    fun download(model: CatalogModel) {
        scope.launch {
            mutex.withLock {
                val usable = spaceProvider()
                if (!ModelStorage.hasEnoughSpace(usable, model.sizeBytes)) {
                    setStateLocked(
                        model,
                        ModelState.Error(
                            model.id,
                            "لا توجد مساحة كافية: يلزم حوالي " +
                                "${ModelStorage.requiredBytes(model.sizeBytes) / (1024 * 1024)} " +
                                "ميجابايت والمتاح ${usable / (1024 * 1024)} ميجابايت"
                        )
                    )
                    return@withLock
                }
                // Drop any previous download for this model before queuing
                // a new one so no orphan transfer is left in DownloadManager.
                cancelDownloadImmediateLocked(model)
                val temp = storage.downloadTempFile(model)
                val downloadId = try {
                    downloader.enqueue(
                        url = model.url,
                        destination = temp,
                        title = model.displayName,
                        description = "موديل المساعد الطبي (${model.license})"
                    )
                } catch (failure: Throwable) {
                    setStateLocked(
                        model,
                        ModelState.Error(model.id, "تعذر بدء التنزيل: ${failure.message}")
                    )
                    return@withLock
                }
                store.putString(downloadKey(model.id), downloadId.toString())
                setStateLocked(
                    model,
                    ModelState.Downloading(model.id, 0L, model.sizeBytes)
                )
                startPollingLocked(model, downloadId)
            }
        }
    }

    fun cancelDownload(modelId: String) {
        scope.launch {
            mutex.withLock {
                val model = modelById(modelId) ?: return@withLock
                val id = store.getString(downloadKey(modelId))
                if (id != null) {
                    val downloadId = id.toLongOrNull()
                    if (downloadId != null) {
                        runCatching { downloader.cancel(downloadId) }
                    }
                    store.remove(downloadKey(modelId))
                }
                cancelPollingLocked(modelId)
                storage.downloadTempFile(model).delete()
                setStateLocked(model, ModelState.NotInstalled)
            }
        }
    }

    fun delete(modelId: String) {
        scope.launch {
            mutex.withLock {
                val model = modelById(modelId) ?: return@withLock
                cancelDownloadImmediateLocked(model)
                storage.deleteInstalled(model)
                setStateLocked(model, ModelState.NotInstalled)
            }
        }
    }

    /**
     * SAF import path: accepts only a stream whose sha256 equals a catalog
     * entry. Unknown or corrupted files are deleted with
     * "الملف غير مطابق للمتوقع".
     */
    suspend fun importFrom(open: () -> InputStream): Boolean = withContext(Dispatchers.IO) {
        mutex.withLock {
            val temp = storage.importTempFile()
            try {
                open().use { input ->
                    temp.outputStream().use { output ->
                        input.copyTo(output, 1 shl 20)
                    }
                }
                val sha = Sha256Util.digestFile(temp)
                val size = temp.length()
                val match = catalog.firstOrNull { it.sha256 == sha }
                if (match == null || size != match.sizeBytes) {
                    temp.delete()
                    val fallback = catalog.first()
                    setStateLocked(fallback, ModelState.Error(fallback.id, MISMATCH_MESSAGE))
                    return@withLock false
                }
                storage.moveIntoPlace(temp, match)
                store.remove(downloadKey(match.id))
                setStateLocked(
                    match,
                    ModelState.Ready(match.id, match.fileName, match.sizeBytes)
                )
                true
            } catch (cancellation: kotlinx.coroutines.CancellationException) {
                temp.delete()
                throw cancellation
            } catch (failure: Throwable) {
                temp.delete()
                val fallback = catalog.first()
                setStateLocked(
                    fallback,
                    ModelState.Error(
                        fallback.id,
                        "تعذر استيراد الملف: ${failure.message ?: failure.javaClass.simpleName}"
                    )
                )
                false
            }
        }
    }

    private fun downloadKey(modelId: String) = "download_id_$modelId"

    private fun startPollingLocked(model: CatalogModel, downloadId: Long) {
        cancelPollingLocked(model.id)
        pollingJobs[model.id] = scope.launch {
            while (true) {
                val done: Boolean = mutex.withLock {
                    val temp = storage.downloadTempFile(model)
                    when (val status = downloader.query(downloadId, temp)) {
                        is DownloadStatus.Successful -> {
                            finalizeLocked(model, status.file)
                            true
                        }
                        is DownloadStatus.Failed -> {
                            cleanupLocked(model, downloadId)
                            setStateLocked(
                                model,
                                ModelState.Error(model.id, "فشل التنزيل: ${status.reason}")
                            )
                            true
                        }
                        is DownloadStatus.Unknown -> {
                            // Cancelled from the system UI or expired.
                            cleanupLocked(model, downloadId)
                            true
                        }
                        is DownloadStatus.Running -> {
                            setStateLocked(
                                model,
                                ModelState.Downloading(
                                    model.id,
                                    status.bytesSoFar,
                                    if (status.totalBytes > 0) status.totalBytes else model.sizeBytes
                                )
                            )
                            false
                        }
                        DownloadStatus.Paused, DownloadStatus.Pending -> {
                            setStateLocked(
                                model,
                                ModelState.Downloading(model.id, 0L, model.sizeBytes)
                            )
                            false
                        }
                    }
                }
                if (done) return@launch
                delay(pollMs)
            }
        }
    }

    /**
     * Verifies size + sha256, then moves the file into filesDir/models.
     * Idempotent: if the final file is already present and valid the temp
     * is dropped and the state becomes Ready again. Blocking file IO is
     * fine here because it always runs on the manager's IO dispatcher.
     */
    private fun finalizeLocked(model: CatalogModel, temp: File) {
        setStateLocked(model, ModelState.Verifying(model.id))
        val finalFile = storage.finalFile(model)
        if (finalFile.isFile && finalFile.length() == model.sizeBytes &&
            Sha256Util.digestFile(finalFile) == model.sha256
        ) {
            temp.delete()
            store.remove(downloadKey(model.id))
            cancelPollingLocked(model.id)
            setStateLocked(
                model,
                ModelState.Ready(model.id, finalFile.name, finalFile.length())
            )
            return
        }
        if (!temp.isFile || temp.length() != model.sizeBytes) {
            temp.delete()
            store.remove(downloadKey(model.id))
            cancelPollingLocked(model.id)
            setStateLocked(model, ModelState.Error(model.id, MISMATCH_MESSAGE))
            return
        }
        val sha = Sha256Util.digestFile(temp)
        if (sha != model.sha256) {
            temp.delete()
            store.remove(downloadKey(model.id))
            cancelPollingLocked(model.id)
            setStateLocked(model, ModelState.Error(model.id, MISMATCH_MESSAGE))
            return
        }
        val moved = storage.moveIntoPlace(temp, model)
        store.remove(downloadKey(model.id))
        cancelPollingLocked(model.id)
        setStateLocked(
            model,
            ModelState.Ready(model.id, moved.name, moved.length())
        )
    }

    private fun cleanupLocked(model: CatalogModel, downloadId: Long) {
        runCatching { downloader.cancel(downloadId) }
        store.remove(downloadKey(model.id))
        cancelPollingLocked(model.id)
        storage.downloadTempFile(model).delete()
    }

    private fun cancelDownloadImmediateLocked(model: CatalogModel) {
        val id = store.getString(downloadKey(model.id))
        if (id != null) {
            val downloadId = id.toLongOrNull()
            if (downloadId != null) {
                runCatching { downloader.cancel(downloadId) }
            }
            store.remove(downloadKey(model.id))
        }
        cancelPollingLocked(model.id)
        storage.downloadTempFile(model).delete()
    }

    private fun cancelPollingLocked(modelId: String) {
        pollingJobs.remove(modelId)?.cancel()
    }

    private fun setStateLocked(model: CatalogModel, state: ModelState) {
        _states.update { current ->
            current + (model.id to state)
        }
    }

    /** Screenshot support: renders a state through the same UI path. */
    fun injectStateForUiTest(modelId: String, state: ModelState) {
        _states.update { current -> current + (modelId to state) }
    }

    /** Screenshot support: clean slate for the "not installed" state. */
    fun resetForUiTest() {
        scope.launch {
            mutex.withLock {
                for (model in catalog) {
                    cancelDownloadImmediateLocked(model)
                    storage.deleteInstalled(model)
                }
                _states.value =
                    catalog.associate { it.id to ModelState.NotInstalled as ModelState }
            }
        }
    }

    companion object {
        const val MISMATCH_MESSAGE = "الملف غير مطابق للمتوقع"
    }
}
