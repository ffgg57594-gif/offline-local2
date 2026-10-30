package com.offlinemedical.chat.util

object AppConfig {
    const val MODEL_DOWNLOAD_URL = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    const val STRICT_SIMILARITY_THRESHOLD = 0.62f
    const val VERIFICATION_THRESHOLD = 0.55f
    const val MAX_QUERY_TOKENS = 512
    const val N_CTX = 2048
    const val N_BATCH = 512
}
