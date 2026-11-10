package com.medai.assistant.llm.download

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import java.io.File

/**
 * K7a: real DownloadManager-backed downloader.
 *
 * Android's DownloadManager keeps the transfer alive across process death
 * and app restarts, resumes after connectivity loss, retries on HTTP
 * errors, and shows a system progress notification (hence POST_NOTIFICATIONS
 * on API 33+). Downloads go to app-specific external storage so no storage
 * permission is required. The destination [File] is supplied by the caller
 * because COLUMN_LOCAL_FILENAME is hidden from modern apps; on restart the
 * caller reconstructs it from the catalog.
 */
class AndroidModelDownloader(
    private val context: Context
) : ModelDownloader {

    private val downloadManager: DownloadManager =
        context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager

    override fun enqueue(
        url: String,
        destination: File,
        title: String,
        description: String
    ): Long {
        destination.parentFile?.mkdirs()
        val request = DownloadManager.Request(Uri.parse(url))
            .setTitle(title)
            .setDescription(description)
            .setDestinationUri(Uri.fromFile(destination))
            .setAllowedNetworkTypes(
                DownloadManager.Request.NETWORK_WIFI or
                    DownloadManager.Request.NETWORK_MOBILE
            )
            .setAllowedOverMetered(true)
            .setAllowedOverRoaming(false)
            .setNotificationVisibility(
                DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
            )
        // HTTPS-only URLs are enforced by ModelCatalog; the network security
        // config additionally forbids cleartext for the whole app.
        return downloadManager.enqueue(request)
    }

    override fun query(id: Long, destination: File): DownloadStatus {
        val query = DownloadManager.Query().setFilterById(id)
        downloadManager.query(query).use { cursor ->
            if (!cursor.moveToFirst()) {
                return DownloadStatus.Unknown
            }
            val bytesSoFar =
                cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
            val totalBytes =
                cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
            return when (cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))) {
                DownloadManager.STATUS_SUCCESSFUL -> DownloadStatus.Successful(destination)
                DownloadManager.STATUS_FAILED -> {
                    val reason = cursor.getInt(
                        cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON)
                    )
                    DownloadStatus.Failed("DownloadManager error $reason")
                }
                DownloadManager.STATUS_PAUSED -> DownloadStatus.Paused
                DownloadManager.STATUS_RUNNING -> DownloadStatus.Running(bytesSoFar, totalBytes)
                DownloadManager.STATUS_PENDING -> DownloadStatus.Pending
                else -> DownloadStatus.Unknown
            }
        }
    }

    override fun cancel(id: Long) {
        // Also removes the partially downloaded file.
        downloadManager.remove(id)
    }
}
