package com.medai.assistant.llm

import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Fixed sampling: greedy + repeat_penalty 1.1 + top_p 0.1. */
data class GenerationStats(
    val promptTokens: Int,
    val outputTokens: Int,
    val timeToFirstTokenMs: Long,
    val totalMs: Long,
    val tokensPerSecond: Double
)

data class ModelInfo(
    val desc: String,
    val sizeBytes: Long,
    val nCtxTrain: Int,
    val nCtx: Int,
    val nVocab: Int,
    val hasChatTemplate: Boolean,
    val template: String
)

/**
 * K7a: one loaded llama.cpp model.
 *
 * All native work (load, generate, free) runs on one dedicated engine
 * thread so nothing blocks the main thread; [cancel] may be called from
 * any thread at any time. Freeing is safe twice and waits for any
 * running generation to unwind first.
 */
class LlamaEngine private constructor(
    val handle: Long,
    val modelPath: String,
    val loadMs: Long,
    val nThreads: Int,
    private val executor: ExecutorService,
    val modelInfo: ModelInfo
) {

    private val freed = AtomicBoolean(false)
    private val freeLock = Any()

    /** True when the run finished normally; false when cancelled. */
    data class GenerationResult(
        val completed: Boolean,
        val stats: GenerationStats
    )

    fun cancel() = synchronized(freeLock) {
        if (!freed.get()) {
            LlamaBridge.nativeCancel(handle)
        }
    }

    /**
     * Streams [onToken] from the engine thread; make sure the receiver is
     * thread-safe (e.g. a MutableStateFlow).
     */
    suspend fun generate(
        prompt: String,
        maxTokens: Int,
        onToken: (String) -> Unit
    ): GenerationResult {
        check(!freed.get()) { "المحرك محرر بالفعل" }
        val sink = LlamaBridge.TokenSink { piece -> onToken(piece) }
        return suspendCancellableCoroutine { continuation ->
            val future = executor.submit {
                val completed = try {
                    LlamaBridge.nativeGenerate(handle, prompt, maxTokens, sink)
                } catch (failure: Throwable) {
                    continuation.resumeWithException(failure)
                    return@submit
                }
                val stats = try {
                    parseStats(LlamaBridge.nativeStatsJson(handle))
                } catch (failure: Throwable) {
                    continuation.resumeWithException(failure)
                    return@submit
                }
                continuation.resume(GenerationResult(completed, stats))
            }
            continuation.invokeOnCancellation {
                cancel()
                future.cancel(false)
            }
        }
    }

    /**
     * Cancels any in-flight generation, frees native memory, and joins.
     *
     * [freeLock] makes nativeCancel/nativeFree call ordering race-free:
     * once `freed` flips to true under the lock no other thread can touch
     * the native handle again (double free / use-after-free are both
     * impossible).
     */
    fun free() {
        val proceed = synchronized(freeLock) {
            if (freed.getAndSet(true)) {
                false
            } else {
                // Ask any running generation to stop before the handle dies.
                LlamaBridge.nativeCancel(handle)
                true
            }
        }
        if (!proceed) return
        runCatching {
            executor.submit { LlamaBridge.nativeFree(handle) }.get(FREE_TIMEOUT_S, TimeUnit.SECONDS)
        }
        executor.shutdownNow()
    }

    companion object {
        const val DEFAULT_N_CTX = 2048
        const val DEFAULT_N_BATCH = 512

        /** Cooperative load cancellation flag. */
        @Volatile
        var loadCancelRequested = false

        suspend fun load(
            path: String,
            nCtx: Int = DEFAULT_N_CTX,
            nBatch: Int = DEFAULT_N_BATCH,
            nThreads: Int = BigCores.count(),
            onProgress: (Float) -> Unit = {}
        ): LlamaEngine {
            check(nCtx > 0 && nBatch > 0 && nThreads > 0) { "invalid engine params" }
            loadCancelRequested = false
            val executor = Executors.newSingleThreadExecutor { runnable ->
                Thread(runnable, "llama-engine").apply { isDaemon = true }
            }
            return suspendCancellableCoroutine { continuation ->
                executor.execute {
                    val start = System.nanoTime()
                    val listener = LlamaBridge.LoadProgressListener { fraction ->
                        onProgress(fraction)
                        !loadCancelRequested
                    }
                    val handle = try {
                        LlamaBridge.nativeLoad(path, nCtx, nBatch, nThreads, listener)
                    } catch (failure: Throwable) {
                        executor.shutdownNow()
                        continuation.resumeWithException(failure)
                        return@execute
                    }
                    val loadMs = (System.nanoTime() - start) / 1_000_000
                    if (handle == 0L) {
                        executor.shutdownNow()
                        continuation.resumeWithException(
                            IllegalStateException("فشل تحميل الموديل من $path")
                        )
                        return@execute
                    }
                    val info = try {
                        parseModelInfo(LlamaBridge.nativeModelInfoJson(handle))
                    } catch (failure: Throwable) {
                        LlamaBridge.nativeFree(handle)
                        executor.shutdownNow()
                        continuation.resumeWithException(failure)
                        return@execute
                    }
                    continuation.resume(
                        LlamaEngine(handle, path, loadMs, nThreads, executor, info)
                    )
                }
                continuation.invokeOnCancellation {
                    loadCancelRequested = true
                }
            }
        }

        private fun parseStats(json: String): GenerationStats {
            val obj = JSONObject(json)
            return GenerationStats(
                promptTokens = obj.getInt("prompt_tokens"),
                outputTokens = obj.getInt("output_tokens"),
                timeToFirstTokenMs = obj.getLong("ttft_ms"),
                totalMs = obj.getLong("total_ms"),
                tokensPerSecond = obj.getDouble("tokens_per_second")
            )
        }

        private fun parseModelInfo(json: String): ModelInfo {
            val obj = JSONObject(json)
            return ModelInfo(
                desc = obj.optString("desc"),
                sizeBytes = obj.getLong("size_bytes"),
                nCtxTrain = obj.getInt("n_ctx_train"),
                nCtx = obj.getInt("n_ctx"),
                nVocab = obj.getInt("n_vocab"),
                hasChatTemplate = obj.getBoolean("has_chat_template"),
                template = obj.optString("template")
            )
        }

        private const val FREE_TIMEOUT_S = 30L
    }
}
