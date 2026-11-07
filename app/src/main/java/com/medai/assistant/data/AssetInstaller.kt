package com.medai.assistant.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.security.MessageDigest
import java.util.Locale

sealed interface InstallState {
    data object Idle : InstallState
    data class Copying(val fileName: String, val doneBytes: Long, val totalBytes: Long) : InstallState
    data class Ready(val dir: File) : InstallState
    data class Failed(val message: String) : InstallState
}

interface AssetSource {
    fun open(fileName: String): InputStream
    fun getManifestText(): String
    fun getAvailableFreeSpace(): Long
}

class ContextAssetSource(
    private val context: Context,
    private val manifestName: String = "assets_manifest.json"
) : AssetSource {
    override fun open(fileName: String): InputStream {
        return context.assets.open(fileName)
    }

    override fun getManifestText(): String {
        return context.assets.open(manifestName).use { input ->
            input.bufferedReader(Charsets.UTF_8).readText()
        }
    }

    override fun getAvailableFreeSpace(): Long {
        return context.filesDir.usableSpace
    }
}

class AssetInstaller(
    private val targetBaseDir: File,
    private val assetSource: AssetSource
) {
    private val _installState = MutableStateFlow<InstallState>(InstallState.Idle)
    val installState: StateFlow<InstallState> = _installState.asStateFlow()

    data class AssetInfo(
        val name: String,
        val size: Long,
        val sha256: String
    )

    private fun isBigAsset(name: String): Boolean = isBigAssetName(name)

    suspend fun install(): File = withContext(Dispatchers.IO) {
        try {
            _installState.value = InstallState.Idle

            val manifestText = assetSource.getManifestText()
            val manifestHash = computeSha256(manifestText.toByteArray(Charsets.UTF_8))
            val prefix12 = manifestHash.take(12)
            val installDir = File(targetBaseDir, "assets_$prefix12")

            val manifestData = ManifestParser.parse(manifestText)
            val assetList = mutableListOf<AssetInfo>()
            var totalRequiredBytes = 0L

            for (a in manifestData.assets) {
                if (isBigAsset(a.name)) {
                    val info = AssetInfo(a.name, a.size, a.sha256)
                    assetList.add(info)
                    val targetFile = File(installDir, a.name)
                    if (!isExactMatch(targetFile, info)) {
                        totalRequiredBytes += a.size
                    }
                }
            }

            // Check free space with a buffer (safety margin of 5 MB)
            val freeSpace = assetSource.getAvailableFreeSpace()
            val safetyMargin = 5 * 1024 * 1024L
            if (freeSpace < (totalRequiredBytes + safetyMargin)) {
                val errorMsg = "Insufficient disk space: required $totalRequiredBytes bytes, available $freeSpace bytes"
                _installState.value = InstallState.Failed(errorMsg)
                throw IllegalStateException(errorMsg)
            }

            if (!installDir.exists()) {
                installDir.mkdirs()
            }

            for (asset in assetList) {
                val destFile = File(installDir, asset.name)
                if (isExactMatch(destFile, asset)) {
                    continue
                }

                destFile.parentFile?.mkdirs()
                val tempFile = File(destFile.parentFile, "${destFile.name}.tmp")
                if (tempFile.exists()) {
                    tempFile.delete()
                }

                try {
                    copyAssetStreaming(asset, tempFile)
                    // Verify temp file hash before rename
                    val tempHash = computeFileSha256(tempFile)
                    if (tempHash != asset.sha256) {
                        tempFile.delete()
                        val msg = "Hash mismatch for ${asset.name}: expected ${asset.sha256}, got $tempHash"
                        _installState.value = InstallState.Failed(msg)
                        throw IllegalStateException(msg)
                    }

                    if (destFile.exists()) {
                        destFile.delete()
                    }
                    if (!tempFile.renameTo(destFile)) {
                        // Fallback copy if renameTo fails across file boundaries
                        tempFile.copyTo(destFile, overwrite = true)
                        tempFile.delete()
                    }
                } catch (e: Exception) {
                    if (tempFile.exists()) {
                        tempFile.delete()
                    }
                    throw e
                }
            }

            _installState.value = InstallState.Ready(installDir)
            installDir
        } catch (e: Exception) {
            val message = e.message ?: "Asset installation failed"
            _installState.value = InstallState.Failed(message)
            throw e
        }
    }

    private fun isExactMatch(file: File, asset: AssetInfo): Boolean {
        if (!file.exists()) return false
        if (file.length() != asset.size) return false
        val hash = computeFileSha256(file)
        return hash == asset.sha256
    }

    private fun copyAssetStreaming(asset: AssetInfo, tempFile: File) {
        val buffer = ByteArray(64 * 1024)
        var doneBytes = 0L
        assetSource.open(asset.name).use { input ->
            FileOutputStream(tempFile).use { output ->
                while (true) {
                    val read = input.read(buffer)
                    if (read == -1) break
                    output.write(buffer, 0, read)
                    doneBytes += read
                    _installState.value = InstallState.Copying(asset.name, doneBytes, asset.size)
                }
                output.flush()
            }
        }
    }

    companion object {
        private fun isBigAssetName(name: String): Boolean {
            return name == "books_knowledge.db" ||
                    name == "embeddings.bin" ||
                    name.startsWith("models/")
        }

        /**
         * Re-hashes every installed big asset and compares it with the manifest.
         * Returns "PASS (n files)" or a compact "FAIL: ..." string for the
         * diagnostics report.
         */
        fun verifyInstalledAssets(installDir: File, manifestText: String): String {
            val manifest = ManifestParser.parse(manifestText)
            val problems = mutableListOf<String>()
            var checked = 0
            for (asset in manifest.assets) {
                if (!isBigAssetName(asset.name)) continue
                checked++
                val file = File(installDir, asset.name)
                if (!file.exists()) {
                    problems.add("${asset.name}: missing")
                    continue
                }
                if (file.length() != asset.size) {
                    problems.add("${asset.name}: size ${file.length()} != ${asset.size}")
                    continue
                }
                if (computeFileSha256(file) != asset.sha256) {
                    problems.add("${asset.name}: sha256 mismatch")
                }
            }
            return if (problems.isEmpty()) {
                "PASS ($checked files)"
            } else {
                "FAIL: " + problems.joinToString("; ")
            }
        }

        fun computeSha256(bytes: ByteArray): String {
            val md = MessageDigest.getInstance("SHA-256")
            val digest = md.digest(bytes)
            return digest.joinToString("") { String.format(Locale.ROOT, "%02x", it) }
        }

        fun computeFileSha256(file: File): String {
            val md = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(64 * 1024)
            FileInputStream(file).use { fis ->
                while (true) {
                    val read = fis.read(buffer)
                    if (read == -1) break
                    md.update(buffer, 0, read)
                }
            }
            return md.digest().joinToString("") { String.format(Locale.ROOT, "%02x", it) }
        }
    }
}
