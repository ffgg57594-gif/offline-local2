package com.medai.assistant.llm

import com.medai.assistant.llm.download.DownloadStatus
import com.medai.assistant.llm.download.ModelDownloader
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.util.ArrayDeque

/**
 * K7a: ModelManager state machine with a fake downloader. Covers download
 * progress, sha256 verification, mismatch rejection, cancel, delete,
 * resume-after-restart, free-space checks, and SAF import accept/reject.
 */
class ModelManagerTest {

    @get:Rule
    val temp = TemporaryFolder()

    private lateinit var storage: ModelStorage
    private lateinit var fake: FakeDownloader
    private lateinit var store: InMemoryStore

    private fun newManager(space: () -> Long = { 10_000_000_000L }): ModelManager {
        storage = ModelStorage(temp.newFolder(), temp.newFolder())
        fake = FakeDownloader()
        store = InMemoryStore()
        return ModelManager(
            catalog = listOf(smallModel, tinyModel),
            storage = storage,
            downloader = fake,
            store = store,
            spaceProvider = space,
            pollMs = 5L
        )
    }

    private val content = "A model file body. ".repeat(5000) // 100_000 bytes

    private val smallModel = CatalogModel(
        id = "small-model",
        displayName = "Small model",
        fileName = "small-model.gguf",
        repo = "o/small",
        url = "https://huggingface.co/o/small/resolve/main/small-model.gguf",
        sizeBytes = content.length.toLong(),
        sha256 = Sha256Util.digestBytes(content.toByteArray(Charsets.UTF_8)),
        license = "mit",
        licenseLine = "license: mit",
        licenseUrl = "https://huggingface.co/o/small/blob/main/LICENSE",
        ramEstimateMb = 200,
        ramEstimateCalc = "test",
        isDefault = true
    )

    private val tinyModel = CatalogModel(
        id = "tiny-model",
        displayName = "Tiny model",
        fileName = "tiny-model.gguf",
        repo = "o/tiny",
        url = "https://huggingface.co/o/tiny/resolve/main/tiny-model.gguf",
        sizeBytes = 12L,
        sha256 = "11".repeat(32),
        license = "mit",
        licenseLine = "license: mit",
        licenseUrl = "https://huggingface.co/o/tiny/blob/main/LICENSE",
        ramEstimateMb = 100,
        ramEstimateCalc = "test",
        isDefault = false
    )

    /** Scripts what the fake DownloadManager reports for the next enqueued id. */
    private fun FakeDownloader.script(vararg statuses: DownloadStatus) {
        scriptFor(nextId, statuses.toList())
    }

    private suspend fun awaitState(
        manager: ModelManager,
        modelId: String,
        check: (ModelState) -> Boolean
    ): ModelState = withTimeout(10_000) {
        manager.states.first { map -> check(map[modelId] ?: ModelState.NotInstalled) }
            .let { map -> map[modelId] ?: ModelState.NotInstalled }
    }

    @Test
    fun downloadSucceedsVerifiesAndInstalls() = runBlocking {
        val manager = newManager()
        fake.onSuccessful = { _, destination -> destination.writeBytes(content.toByteArray()) }
        fake.script(
            DownloadStatus.Running(0L, smallModel.sizeBytes),
            DownloadStatus.Running(smallModel.sizeBytes / 2, smallModel.sizeBytes),
            DownloadStatus.Successful(storage.downloadTempFile(smallModel))
        )
        manager.download(smallModel)

        val downloading = awaitState(manager, smallModel.id) { it is ModelState.Downloading }
        assertTrue((downloading as ModelState.Downloading).bytesSoFar >= 0)
        val ready = awaitState(manager, smallModel.id) { it is ModelState.Ready } as ModelState.Ready
        assertEquals("small-model.gguf", ready.fileName)
        assertEquals(smallModel.sizeBytes, ready.sizeBytes)
        val installed = storage.finalFile(smallModel)
        assertTrue(installed.isFile)
        assertEquals(smallModel.sha256, Sha256Util.digestFile(installed))
        // The persisted download id is cleared once installed.
        assertEquals(null, store.getString("download_id_${smallModel.id}"))
    }

    @Test
    fun corruptDownloadIsRejectedAndDeleted() = runBlocking {
        val manager = newManager()
        val corrupted = content.toByteArray().also { it[100] = (it[100].toInt() xor 0x40).toByte() }
        fake.onSuccessful = { _, destination -> destination.writeBytes(corrupted) }
        fake.script(DownloadStatus.Successful(storage.downloadTempFile(smallModel)))
        manager.download(smallModel)

        val error = awaitState(manager, smallModel.id) { it is ModelState.Error } as ModelState.Error
        assertEquals(ModelManager.MISMATCH_MESSAGE, error.message)
        assertFalse(storage.finalFile(smallModel).exists())
        assertFalse(storage.downloadTempFile(smallModel).exists())
    }

    @Test
    fun wrongSizeDownloadIsRejected() = runBlocking {
        val manager = newManager()
        fake.onSuccessful = { _, destination ->
            destination.writeBytes(ByteArray(content.length - 1) { 'x'.code.toByte() })
        }
        fake.script(DownloadStatus.Successful(storage.downloadTempFile(smallModel)))
        manager.download(smallModel)

        val error = awaitState(manager, smallModel.id) { it is ModelState.Error } as ModelState.Error
        assertEquals(ModelManager.MISMATCH_MESSAGE, error.message)
    }

    @Test
    fun failedDownloadReportsError() = runBlocking {
        val manager = newManager()
        fake.script(
            DownloadStatus.Running(10L, smallModel.sizeBytes),
            DownloadStatus.Failed("DownloadManager error 404")
        )
        manager.download(smallModel)

        val error = awaitState(manager, smallModel.id) { it is ModelState.Error } as ModelState.Error
        assertTrue(error.message.contains("404"))
    }

    @Test
    fun cancelDownloadStopsPollingAndClearsState() = runBlocking {
        val manager = newManager()
        fake.script(
            DownloadStatus.Running(0L, smallModel.sizeBytes),
            DownloadStatus.Running(smallModel.sizeBytes / 4, smallModel.sizeBytes)
        )
        manager.download(smallModel)
        awaitState(manager, smallModel.id) { it is ModelState.Downloading }

        manager.cancelDownload(smallModel.id)
        val cancelled = awaitState(manager, smallModel.id) { it is ModelState.NotInstalled }
        assertEquals(ModelState.NotInstalled, cancelled)
        assertTrue(fake.cancelled.isNotEmpty())
        assertEquals(null, store.getString("download_id_${smallModel.id}"))
    }

    @Test
    fun insufficientSpaceFailsBeforeEnqueue() = runBlocking {
        val manager = newManager(space = { 10L })
        manager.download(smallModel)
        val error = awaitState(manager, smallModel.id) { it is ModelState.Error } as ModelState.Error
        assertTrue(error.message.contains("مساحة"))
        assertTrue(fake.enqueued.isEmpty())
    }

    @Test
    fun resumeOnStartReattachesToPersistedDownload() = runBlocking {
        // First manager "dies" mid-download after persisting the id.
        val first = newManager()
        fake.sticky = DownloadStatus.Running(0L, smallModel.sizeBytes)
        first.download(smallModel)
        awaitState(first, smallModel.id) { it is ModelState.Downloading }
        val persistedId = store.getString("download_id_${smallModel.id}")
        assertTrue(persistedId != null)

        // A new manager with the same store and a fresh fake downloader
        // simulates the app restart.
        storage = ModelStorage(temp.newFolder(), temp.newFolder())
        val restartedFake = FakeDownloader().also {
            it.scriptFor(
                persistedId!!.toLong(),
                listOf(
                    DownloadStatus.Running(1L, smallModel.sizeBytes),
                    DownloadStatus.Running(smallModel.sizeBytes / 2, smallModel.sizeBytes)
                )
            )
        }
        val second = ModelManager(
            catalog = listOf(smallModel, tinyModel),
            storage = storage,
            downloader = restartedFake,
            store = store,
            spaceProvider = { 10_000_000_000L },
            pollMs = 5L
        )
        second.resumeOnStart()
        val downloading = awaitState(second, smallModel.id) { it is ModelState.Downloading }
        assertTrue((downloading as ModelState.Downloading).bytesSoFar > 0)
    }

    @Test
    fun resumeOnStartFinalizesCompletedDownload() = runBlocking {
        val first = newManager()
        fake.sticky = DownloadStatus.Running(0L, smallModel.sizeBytes)
        first.download(smallModel)
        awaitState(first, smallModel.id) { it is ModelState.Downloading }
        val persistedId = store.getString("download_id_${smallModel.id}")!!

        storage = ModelStorage(temp.newFolder(), temp.newFolder())
        val restartedFake = FakeDownloader().also {
            it.scriptFor(persistedId.toLong(), listOf(DownloadStatus.Successful(storage.downloadTempFile(smallModel))))
            it.onSuccessful = { _, destination -> destination.writeBytes(content.toByteArray()) }
        }
        val second = ModelManager(
            catalog = listOf(smallModel, tinyModel),
            storage = storage,
            downloader = restartedFake,
            store = store,
            spaceProvider = { 10_000_000_000L },
            pollMs = 5L
        )
        second.resumeOnStart()
        val ready = awaitState(second, smallModel.id) { it is ModelState.Ready } as ModelState.Ready
        assertEquals("small-model.gguf", ready.fileName)
    }

    @Test
    fun resumeOnStartDropsUnknownDownloads() = runBlocking {
        val first = newManager()
        fake.sticky = DownloadStatus.Running(0L, smallModel.sizeBytes)
        first.download(smallModel)
        awaitState(first, smallModel.id) { it is ModelState.Downloading }
        val persistedId = store.getString("download_id_${smallModel.id}")!!

        storage = ModelStorage(temp.newFolder(), temp.newFolder())
        val second = ModelManager(
            catalog = listOf(smallModel, tinyModel),
            storage = storage,
            downloader = FakeDownloader(), // knows nothing about the id
            store = store,
            spaceProvider = { 10_000_000_000L },
            pollMs = 5L
        )
        second.resumeOnStart()
        val state = awaitState(second, smallModel.id) { it is ModelState.NotInstalled }
        assertEquals(ModelState.NotInstalled, state)
    }

    @Test
    fun importAcceptsCatalogSha256() = runBlocking {
        val manager = newManager()
        val accepted = manager.importFrom { ByteArrayInputStream(content.toByteArray()) }
        assertTrue(accepted)
        val ready = awaitState(manager, smallModel.id) { it is ModelState.Ready } as ModelState.Ready
        assertEquals("small-model.gguf", ready.fileName)
        assertTrue(storage.finalFile(smallModel).isFile)
        // No leftover import temp files.
        assertEquals(0, storage.modelsDir.listFiles { f -> f.name.contains("import-") }!!.size)
    }

    @Test
    fun importRejectsUnknownFile() = runBlocking {
        val manager = newManager()
        val unknown = "nothing in the catalog matches this".repeat(10)
        val accepted = manager.importFrom { ByteArrayInputStream(unknown.toByteArray()) }
        assertFalse(accepted)
        val error = awaitState(manager, smallModel.id) { it is ModelState.Error } as ModelState.Error
        assertEquals(ModelManager.MISMATCH_MESSAGE, error.message)
        assertEquals(0, storage.modelsDir.listFiles { f -> f.name.contains("import-") }!!.size)
    }

    @Test
    fun importRejectsCorruptedCatalogFile() = runBlocking {
        val manager = newManager()
        val corrupted = content.toByteArray().also { it[5] = (it[5].toInt() xor 0x20).toByte() }
        val accepted = manager.importFrom { ByteArrayInputStream(corrupted) }
        assertFalse(accepted)
        val error = awaitState(manager, smallModel.id) { it is ModelState.Error } as ModelState.Error
        assertEquals(ModelManager.MISMATCH_MESSAGE, error.message)
    }

    @Test
    fun importPropagatesOpenFailure() = runBlocking {
        val manager = newManager()
        val accepted = manager.importFrom { error("no such file") }
        assertFalse(accepted)
        val error = awaitState(manager, smallModel.id) { it is ModelState.Error } as ModelState.Error
        assertTrue(error.message.contains("تعذر استيراد الملف"))
    }

    @Test
    fun deleteRemovesInstalledFile() = runBlocking {
        val manager = newManager()
        fake.onSuccessful = { _, destination -> destination.writeBytes(content.toByteArray()) }
        fake.script(DownloadStatus.Successful(storage.downloadTempFile(smallModel)))
        manager.download(smallModel)
        awaitState(manager, smallModel.id) { it is ModelState.Ready }

        manager.delete(smallModel.id)
        val state = awaitState(manager, smallModel.id) { it is ModelState.NotInstalled }
        assertEquals(ModelState.NotInstalled, state)
        assertFalse(storage.finalFile(smallModel).exists())
    }

    @Test
    fun refreshMarksExistingFilesReady() = runBlocking {
        val manager = newManager()
        storage.finalFile(smallModel).let { file ->
            file.parentFile!!.mkdirs()
            file.writeBytes(content.toByteArray())
        }
        manager.refresh()
        val ready = awaitState(manager, smallModel.id) { it is ModelState.Ready } as ModelState.Ready
        assertEquals(smallModel.sizeBytes, ready.sizeBytes)
    }

    /** In-memory downloader used instead of Android's DownloadManager. */
    private class FakeDownloader : ModelDownloader {
        val enqueued = mutableListOf<String>()
        val cancelled = mutableListOf<Long>()
        private val statuses = mutableMapOf<Long, ArrayDeque<DownloadStatus>>()

        var nextId = 1L
            private set

        var onSuccessful: (id: Long, destination: File) -> Unit = { _, _ -> }

        /**
         * Returned once the scripted queue drains so the polled download
         * never turns Unknown mid-test (Unknown triggers the manager's
         * cleanup, which removes the persisted download id the resume
         * tests need to read).
         */
        var sticky: DownloadStatus? = null

        override fun enqueue(
            url: String,
            destination: File,
            title: String,
            description: String
        ): Long {
            val id = nextId++
            enqueued += url
            // A scripted queue (from script()/scriptFor()) wins over the
            // default empty one so tests can pre-program this id.
            if (id !in statuses) {
                statuses[id] = ArrayDeque()
            }
            return id
        }

        override fun query(id: Long, destination: File): DownloadStatus {
            val next = statuses[id]?.pollFirst() ?: sticky ?: return DownloadStatus.Unknown
            if (next is DownloadStatus.Successful) {
                onSuccessful(id, next.file)
            }
            return next
        }

        override fun cancel(id: Long) {
            cancelled += id
        }

        fun scriptFor(id: Long, list: List<DownloadStatus>) {
            statuses[id] = ArrayDeque(list)
        }
    }

    private class InMemoryStore : KeyValueStore {
        val map = LinkedHashMap<String, String>()
        override fun getString(key: String): String? = map[key]
        override fun putString(key: String, value: String) { map[key] = value }
        override fun remove(key: String) { map.remove(key) }
        override fun clear() { map.clear() }
    }
}
