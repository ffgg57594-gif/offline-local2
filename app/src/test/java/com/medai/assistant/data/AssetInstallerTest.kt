package com.medai.assistant.data

import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.io.InputStream

class AssetInstallerTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    private lateinit var targetBaseDir: File

    @Before
    fun setUp() {
        targetBaseDir = tempFolder.newFolder("target_base")
    }

    class FakeAssetSource(
        private val files: Map<String, ByteArray>,
        private var availableSpace: Long = 100 * 1024 * 1024L
    ) : AssetSource {

        private val manifestContent: String

        init {
            val assetList = files.map { (name, bytes) ->
                ManifestAsset(
                    name = name,
                    size = bytes.size.toLong(),
                    sha256 = AssetInstaller.computeSha256(bytes)
                )
            }
            manifestContent = ManifestParser.serialize(
                chunkCount = 1185,
                chunkTextsSha256 = "dummy",
                assets = assetList
            )
        }

        override fun open(fileName: String): InputStream {
            val bytes = files[fileName] ?: throw IllegalArgumentException("File not found: $fileName")
            return ByteArrayInputStream(bytes)
        }

        override fun getManifestText(): String {
            return manifestContent
        }

        override fun getAvailableFreeSpace(): Long {
            return availableSpace
        }

        fun setFreeSpace(space: Long) {
            availableSpace = space
        }
    }

    @Test
    fun testCopiesWhenMissingAndMatchesHash() = runBlocking {
        val dummyDb = "SQLite format 3\u0000".toByteArray(Charsets.UTF_8)
        val dummyBin = ByteArray(256) { it.toByte() }
        val dummyOnnx = ByteArray(512) { (it % 100).toByte() }

        val fakeFiles = mapOf(
            "books_knowledge.db" to dummyDb,
            "embeddings.bin" to dummyBin,
            "models/embedder/model_quantized.onnx" to dummyOnnx
        )

        val source = FakeAssetSource(fakeFiles)
        val installer = AssetInstaller(targetBaseDir, source)

        val states = mutableListOf<InstallState>()
        val job = launch {
            installer.installState.toList(states)
        }

        val installedDir = installer.install()
        assertTrue("Installed dir should exist", installedDir.exists())

        // Verify files exist with exact hashes
        for ((name, bytes) in fakeFiles) {
            val file = File(installedDir, name)
            assertTrue("File $name should exist", file.exists())
            assertEquals(bytes.size.toLong(), file.length())
            assertEquals(AssetInstaller.computeSha256(bytes), AssetInstaller.computeFileSha256(file))
        }

        assertTrue("Final state should be Ready", installer.installState.value is InstallState.Ready)
        job.cancel()
    }

    @Test
    fun testSkipsWhenHashAlreadyMatches() = runBlocking {
        val dummyDb = "SQLite format 3\u0000SomeData".toByteArray(Charsets.UTF_8)
        val fakeFiles = mapOf("books_knowledge.db" to dummyDb)
        val source = FakeAssetSource(fakeFiles)
        val installer = AssetInstaller(targetBaseDir, source)

        val installedDir = installer.install()
        val file = File(installedDir, "books_knowledge.db")
        assertTrue(file.exists())
        val originalLastModified = file.lastModified()

        // Wait slightly and install again
        Thread.sleep(100)
        val installer2 = AssetInstaller(targetBaseDir, source)
        val installedDir2 = installer2.install()
        val file2 = File(installedDir2, "books_knowledge.db")

        assertEquals(originalLastModified, file2.lastModified())
        assertTrue(installer2.installState.value is InstallState.Ready)
    }

    @Test
    fun testReCopiesOnHashMismatch() = runBlocking {
        val dummyDb = "SQLite format 3\u0000CorrectContent".toByteArray(Charsets.UTF_8)
        val fakeFiles = mapOf("books_knowledge.db" to dummyDb)
        val source = FakeAssetSource(fakeFiles)
        val installer = AssetInstaller(targetBaseDir, source)

        val installedDir = installer.install()
        val file = File(installedDir, "books_knowledge.db")
        assertTrue(file.exists())

        // Corrupt the file
        file.writeText("Corrupted content")
        assertNotEquals(AssetInstaller.computeSha256(dummyDb), AssetInstaller.computeFileSha256(file))

        // Re-run installation
        val installer2 = AssetInstaller(targetBaseDir, source)
        installer2.install()

        // Should be restored to original correct content
        assertEquals(AssetInstaller.computeSha256(dummyDb), AssetInstaller.computeFileSha256(file))
    }

    @Test
    fun testLeavesNoPartialFilesOnFailure() = runBlocking {
        val dummyDb = "SQLite format 3\u0000Data".toByteArray(Charsets.UTF_8)
        val source = object : AssetSource {
            override fun open(fileName: String): InputStream {
                return object : InputStream() {
                    private var count = 0
                    override fun read(): Int {
                        count++
                        if (count > 5) throw java.io.IOException("Simulated transfer failure")
                        return 65
                    }
                }
            }

            override fun getManifestText(): String {
                val assetList = listOf(ManifestAsset("books_knowledge.db", 100L, "dummysha"))
                return ManifestParser.serialize(1185, "dummy", assetList)
            }

            override fun getAvailableFreeSpace(): Long = 50 * 1024 * 1024L
        }

        val installer = AssetInstaller(targetBaseDir, source)
        try {
            installer.install()
            fail("Should have thrown exception on simulated failure")
        } catch (e: Exception) {
            // Expected
        }

        val manifestHash = AssetInstaller.computeSha256(source.getManifestText().toByteArray(Charsets.UTF_8))
        val installDir = File(targetBaseDir, "assets_${manifestHash.take(12)}")

        val tmpFiles = installDir.listFiles { _, name -> name.endsWith(".tmp") } ?: emptyArray()
        assertEquals("No .tmp partial files should be left behind", 0, tmpFiles.size)
        assertTrue("Installer state should be Failed", installer.installState.value is InstallState.Failed)
    }

    @Test
    fun testFailsCleanlyOnLowSpace() = runBlocking {
        val dummyDb = ByteArray(10 * 1024 * 1024) { 1 } // 10 MB
        val fakeFiles = mapOf("books_knowledge.db" to dummyDb)
        val source = FakeAssetSource(fakeFiles, availableSpace = 2 * 1024 * 1024L) // only 2 MB free

        val installer = AssetInstaller(targetBaseDir, source)
        try {
            installer.install()
            fail("Should have failed due to low disk space")
        } catch (e: IllegalStateException) {
            assertTrue(e.message?.contains("Insufficient disk space") == true)
        }

        val state = installer.installState.value
        assertTrue("State should be Failed", state is InstallState.Failed)
        assertTrue((state as InstallState.Failed).message.contains("Insufficient disk space"))
    }

    @Test
    fun testReportsProgressDuringCopy() = runBlocking {
        val dummyBin = ByteArray(500 * 1024) { 42 } // 500 KB
        val fakeFiles = mapOf("embeddings.bin" to dummyBin)
        val source = FakeAssetSource(fakeFiles)
        val installer = AssetInstaller(targetBaseDir, source)

        val states = mutableListOf<InstallState>()
        val job = launch {
            installer.installState.collect { states.add(it) }
        }

        installer.install()
        job.cancel()

        val copyingStates = states.filterIsInstance<InstallState.Copying>()
        assertTrue("Should have reported at least one Copying state", copyingStates.isNotEmpty())
        val lastCopying = copyingStates.last()
        assertEquals("embeddings.bin", lastCopying.fileName)
        assertEquals(500 * 1024L, lastCopying.doneBytes)
        assertEquals(500 * 1024L, lastCopying.totalBytes)
    }
}
