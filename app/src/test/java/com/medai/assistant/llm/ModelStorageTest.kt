package com.medai.assistant.llm

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** K7a: model storage paths, rename flow, and the 1.3x free-space rule. */
class ModelStorageTest {

    @get:Rule
    val temp = TemporaryFolder()

    private fun storage(): ModelStorage = ModelStorage(temp.newFolder(), temp.newFolder())

    private fun model(sizeBytes: Long = 10L): CatalogModel = CatalogModel(
        id = "test-model",
        displayName = "Test model",
        fileName = "test-model.gguf",
        repo = "o/a",
        url = "https://huggingface.co/o/a/resolve/main/test-model.gguf",
        sizeBytes = sizeBytes,
        sha256 = "0".repeat(64),
        license = "mit",
        licenseLine = "license: mit",
        licenseUrl = "https://huggingface.co/o/a/blob/main/LICENSE",
        ramEstimateMb = 100,
        ramEstimateCalc = "test",
        isDefault = true
    )

    @Test
    fun requiredBytesUsesOnePointThreeFactor() {
        assertEquals(1_300_000L, ModelStorage.requiredBytes(1_000_000L))
        assertEquals(1_451_516L, ModelStorage.requiredBytes(1_116_550L))
        assertTrue(ModelStorage.hasEnoughSpace(usableBytes = 1_300_000L, sizeBytes = 1_000_000L))
        assertFalse(ModelStorage.hasEnoughSpace(usableBytes = 1_299_999L, sizeBytes = 1_000_000L))
    }

    @Test
    fun tempAndFinalFilesAreDistinct() {
        val storage = storage()
        val model = model()
        val tempFile = storage.downloadTempFile(model)
        val final = storage.finalFile(model)
        assertTrue(tempFile.name.endsWith(".download"))
        assertEquals("test-model.gguf", final.name)
        assertTrue(final.parentFile!!.absolutePath.contains("models"))
    }

    @Test
    fun moveIntoPlaceRenamesAtomically() {
        val storage = storage()
        val model = model()
        val src = storage.downloadTempFile(model)
        src.parentFile!!.mkdirs()
        src.writeBytes(ByteArray(64) { 1 })
        val moved = storage.moveIntoPlace(src, model)
        assertEquals(storage.finalFile(model), moved)
        assertFalse(src.exists())
        assertEquals(64L, moved.length())
    }

    @Test
    fun moveIntoPlaceFallsBackToCopyAcrossFilesystems() {
        val storage = storage()
        val model = model()
        val src = temp.newFile("elsewhere.bin")
        src.writeBytes(ByteArray(32) { 2 })
        val moved = storage.moveIntoPlace(src, model)
        assertFalse(src.exists())
        assertEquals(32L, moved.length())
    }

    @Test
    fun listInstalledFindsOnlyGgufFiles() {
        val storage = storage()
        val model = model()
        val final = storage.finalFile(model)
        final.parentFile!!.mkdirs()
        final.writeBytes(ByteArray(8))
        storage.importTempFile().writeBytes(ByteArray(8))
        val listed = storage.listInstalled()
        assertEquals(listOf(final.name), listed.map { it.name })
        assertNotNull(storage.installedFileFor(model))
        val otherModel = model().copy(id = "other-model", fileName = "other.gguf")
        assertNull(storage.installedFileFor(otherModel))
    }

    @Test
    fun deleteInstalledRemovesFile() {
        val storage = storage()
        val model = model()
        val final = storage.finalFile(model)
        final.parentFile!!.mkdirs()
        final.writeBytes(ByteArray(8))
        assertTrue(storage.deleteInstalled(model))
        assertFalse(final.exists())
    }
}
