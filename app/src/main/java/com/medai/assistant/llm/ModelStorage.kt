package com.medai.assistant.llm

import java.io.File
import java.io.IOException
import java.util.UUID

/**
 * K7a: where downloaded models live.
 *
 * - DownloadManager writes to [downloadDir] (app-specific external files,
 *   no storage permission needed). The partial file is verified there.
 * - Verified models are moved into [modelsDir] (internal storage) with an
 *   atomic same-filesystem rename.
 *
 * Constructed for JVM tests with temp directories so the space checks and
 * the rename flow can be tested without Android.
 */
class ModelStorage(
    private val filesDir: File,
    private val downloadDir: File?
) {

    val modelsDir: File
        get() = File(filesDir, "models").apply { mkdirs() }

    val scratchDir: File
        get() = (downloadDir ?: modelsDir).apply { mkdirs() }

    fun finalFile(model: CatalogModel): File = File(modelsDir, model.fileName)

    fun downloadTempFile(model: CatalogModel): File =
        File(scratchDir, "${model.id}.download")

    fun importTempFile(): File =
        File(modelsDir, "import-${UUID.randomUUID()}.part")

    fun usableBytes(): Long = scratchDir.usableSpace

    fun internalUsableBytes(): Long = modelsDir.usableSpace

    fun listInstalled(): List<File> =
        modelsDir.listFiles { file -> file.isFile && file.name.endsWith(".gguf") }
            ?.sortedBy { it.name }
            ?: emptyList()

    fun installedFileFor(model: CatalogModel): File? {
        val file = finalFile(model)
        return if (file.isFile && file.length() > 0) file else null
    }

    /**
     * Moves a verified file into place. The rename stays on the same
     * filesystem when possible; otherwise it falls back to copy + delete
     * after a size check.
     */
    @Throws(IOException::class)
    fun moveIntoPlace(temp: File, model: CatalogModel): File {
        val destination = finalFile(model)
        destination.parentFile?.mkdirs()
        if (destination.exists()) {
            destination.delete()
        }
        if (temp.renameTo(destination)) {
            return destination
        }
        temp.copyTo(destination, overwrite = true)
        check(destination.length() == temp.length()) {
            "copy of ${temp.name} changed size: ${temp.length()} -> ${destination.length()}"
        }
        temp.delete()
        return destination
    }

    fun deleteInstalled(model: CatalogModel): Boolean = finalFile(model).delete()

    fun deleteAllInstalled() {
        listInstalled().forEach { it.delete() }
    }

    companion object {
        /** Required free space: 1.3x the model size, per the download plan. */
        const val FREE_SPACE_FACTOR = 1.3

        fun requiredBytes(sizeBytes: Long): Long =
            (sizeBytes.toDouble() * FREE_SPACE_FACTOR).toLong()

        fun hasEnoughSpace(usableBytes: Long, sizeBytes: Long): Boolean =
            usableBytes >= requiredBytes(sizeBytes)
    }
}
