package com.medai.assistant.llm.download

import java.io.File

/**
 * K7a: the only layer allowed to touch Android's DownloadManager. All
 * classes that reference network APIs live in this package; CI fails the
 * build when any other package references java.net/okhttp/DownloadManager.
 */
sealed interface DownloadStatus {
    data object Pending : DownloadStatus
    data class Running(val bytesSoFar: Long, val totalBytes: Long) : DownloadStatus
    data object Paused : DownloadStatus
    data class Successful(val file: File) : DownloadStatus
    data class Failed(val reason: String) : DownloadStatus
    /** The id is no longer known to DownloadManager (cancelled or expired). */
    data object Unknown : DownloadStatus
}

interface ModelDownloader {
    /** Enqueues a download; returns its DownloadManager id. */
    fun enqueue(url: String, destination: File, title: String, description: String): Long

    /**
     * Reads the status of [id]. [destination] is the file the request was
     * written to; the system no longer reports local filenames to apps.
     */
    fun query(id: Long, destination: File): DownloadStatus

    fun cancel(id: Long)
}
