package com.offlinemedical.chat.embedder

import android.content.Context
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class Embedder(private val context: Context, private val modelAsset: String) {
    private val env = OrtEnvironment.getEnvironment()
    private var session: OrtSession? = null
    suspend fun warmUp() = withContext(Dispatchers.Default) {
        // Load model from filesDir; create session with XNNPACK
    }
    suspend fun embed(text: String): FloatArray = withContext(Dispatchers.Default) {
        FloatArray(384) { 0f }
    }
}
