package com.offlinemedical.chat.util

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

object AssetInstaller {
    suspend fun install(context: Context, onProgress: (Float) -> Unit) = withContext(Dispatchers.IO) {
        val assets = context.assets.list("") ?: emptyArray()
        val total = assets.size.coerceAtLeast(1)
        assets.forEachIndexed { i, _ ->
            onProgress((i + 1f) / total)
        }
    }
    fun isInstalled(context: Context): Boolean = File(context.filesDir, "books_knowledge.db").exists()
}
