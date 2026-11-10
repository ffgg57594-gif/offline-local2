package com.medai.assistant.llm

/**
 * K7a: JNI surface for llama.cpp. The native implementation lives in
 * app/src/main/cpp/llama_jni.cpp and links the llama.cpp submodule
 * (external/llama.cpp, git-pinned).
 *
 * The engine's sampling is fixed and deterministic: greedy with
 * repeat_penalty 1.1 (last 64 tokens) and top_p 0.1, and the model's own
 * chat template (ChatML for the Qwen GGUF files; models without a
 * template get the raw prompt).
 */
object LlamaBridge {
    init {
        System.loadLibrary("llama_jni")
    }

    /** Token callback during generation; called on the engine thread. */
    fun interface TokenSink {
        fun onToken(piece: String)
    }

    /** Load progress callback; return false to abort loading. */
    fun interface LoadProgressListener {
        fun onProgress(fraction: Float): Boolean
    }

    /**
     * Loads a GGUF model with mmap. n_ctx is clamped down to the model's
     * trained context when smaller. Returns 0 on failure (the caller
     * turns that into a visible error; llama.cpp logged the reason).
     */
    external fun nativeLoad(
        path: String,
        nCtx: Int,
        nBatch: Int,
        nThreads: Int,
        progress: LoadProgressListener?
    ): Long

    external fun nativeFree(handle: Long)

    /**
     * Generates up to [maxTokens] tokens, streaming pieces to [sink].
     * Returns true when the run completed, false when it was cancelled.
     */
    external fun nativeGenerate(
        handle: Long,
        prompt: String,
        maxTokens: Int,
        sink: TokenSink?
    ): Boolean

    /** Cooperative cancellation; safe to call from any thread at any time. */
    external fun nativeCancel(handle: Long)

    /** JSON stats of the last run on this handle. */
    external fun nativeStatsJson(handle: Long): String

    /** Static model facts as JSON (desc, sizes, context, template). */
    external fun nativeModelInfoJson(handle: Long): String
}
