package com.offlinemedical.chat.ocr

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

object OcrHelper {
    suspend fun recognize(context: Context, imagePath: String): String = withContext(Dispatchers.Default) {
        // Tesseract4Android integration point
        ""
    }
}
