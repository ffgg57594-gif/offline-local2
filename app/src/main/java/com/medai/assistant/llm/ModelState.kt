package com.medai.assistant.llm

/**
 * K7a: per-model UI state for the Settings "الموديل" section. The states
 * survive rotation (StateFlow) and process death (DownloadManager ids and
 * installed files are re-read on start).
 */
sealed interface ModelState {
    /** No verified model file and no active download. */
    data object NotInstalled : ModelState

    /** DownloadManager is fetching the file. */
    data class Downloading(
        val modelId: String,
        val bytesSoFar: Long,
        val totalBytes: Long
    ) : ModelState

    /** The finished file is being hashed and size-checked. */
    data class Verifying(val modelId: String) : ModelState

    /** A verified model file is in filesDir/models. */
    data class Ready(
        val modelId: String,
        val fileName: String,
        val sizeBytes: Long
    ) : ModelState

    /** Download failed, verification failed, or the import was rejected. */
    data class Error(val modelId: String, val message: String) : ModelState
}
