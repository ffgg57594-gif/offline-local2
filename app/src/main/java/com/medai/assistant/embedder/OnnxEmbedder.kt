package com.medai.assistant.embedder

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import com.medai.assistant.tokenizer.Tokenizer
import java.io.Closeable
import java.io.File
import java.nio.LongBuffer
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * ONNX Query Embedder for multilingual-e5-small quantized model.
 * Performs Mean Pooling over attention mask and L2 Normalization.
 */
class OnnxEmbedder(
    modelFile: File,
    private val tokenizer: Tokenizer,
    intraOpThreads: Int = min(4, max(1, Runtime.getRuntime().availableProcessors()))
) : Closeable {

    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    val loadTimeMs: Long
    private val declaredInputNames: Set<String>

    companion object {
        const val EMBED_DIM = 384
        const val MAX_LENGTH = 384
        const val QUERY_PREFIX = "query: "
        const val PASSAGE_PREFIX = "passage: "

        /**
         * Pure function: Mean pooling over attention mask.
         * lastHiddenState: flat array of size [seqLen * dim] (or sequence of floats)
         * attentionMask: array of size [seqLen] (1 for valid token, 0 for padding)
         * Returns: float array of size [dim]
         */
        fun meanPool(
            lastHiddenState: FloatArray,
            attentionMask: LongArray,
            seqLen: Int,
            dim: Int
        ): FloatArray {
            val pooled = FloatArray(dim)
            var maskSum = 0.0

            for (i in 0 until seqLen) {
                if (attentionMask[i] == 1L) {
                    maskSum += 1.0
                    val offset = i * dim
                    for (d in 0 until dim) {
                        pooled[d] += lastHiddenState[offset + d]
                    }
                }
            }

            val divisor = max(maskSum, 1e-9).toFloat()
            for (d in 0 until dim) {
                pooled[d] /= divisor
            }
            return pooled
        }

        /**
         * Pure function: L2 normalization of a float vector.
         */
        fun l2Normalize(vector: FloatArray): FloatArray {
            var sumSq = 0.0
            for (v in vector) {
                sumSq += (v * v).toDouble()
            }
            val norm = max(sqrt(sumSq), 1e-12).toFloat()
            val result = FloatArray(vector.size)
            for (i in vector.indices) {
                result[i] = vector[i] / norm
            }
            return result
        }

        /**
         * Compute cosine similarity between two vectors (for parity checks).
         */
        fun cosineSimilarity(a: FloatArray, b: FloatArray): Float {
            require(a.size == b.size) { "Vectors must have same dimension" }
            var dot = 0.0
            var normA = 0.0
            var normB = 0.0
            for (i in a.indices) {
                dot += a[i].toDouble() * b[i].toDouble()
                normA += a[i].toDouble() * a[i].toDouble()
                normB += b[i].toDouble() * b[i].toDouble()
            }
            val denom = max(sqrt(normA) * sqrt(normB), 1e-12)
            return (dot / denom).toFloat()
        }
    }

    init {
        val start = System.currentTimeMillis()
        val opts = OrtSession.SessionOptions().apply {
            setIntraOpNumThreads(intraOpThreads)
            setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
        }
        session = env.createSession(modelFile.absolutePath, opts)
        loadTimeMs = System.currentTimeMillis() - start
        declaredInputNames = session.inputNames

        // Warm-up run after load
        warmup()
    }

    private fun warmup() {
        embedQuery("warmup")
    }

    /**
     * Embeds a query text.
     * Prepend "query: ", truncate at 384 tokens, run ONNX inference,
     * apply mean pooling over attention mask, and L2 normalize.
     */
    fun embedQuery(question: String): FloatArray = embedWithPrefix(QUERY_PREFIX, question)

    /**
     * Embeds a passage. Only used by parity tests and future indexing tools;
     * the app embeds queries at runtime.
     */
    fun embedPassage(passage: String): FloatArray = embedWithPrefix(PASSAGE_PREFIX, passage)

    private fun embedWithPrefix(prefix: String, question: String): FloatArray {
        val text = prefix + question
        val encoded = tokenizer.encode(text, MAX_LENGTH)

        val seqLen = encoded.ids.size
        val shape = longArrayOf(1L, seqLen.toLong())

        val inputIdsLong = LongArray(seqLen) { i -> encoded.ids[i].toLong() }
        val attentionMaskLong = LongArray(seqLen) { 1L }

        val inputs = mutableMapOf<String, OnnxTensor>()
        val inputIdsTensor = OnnxTensor.createTensor(env, LongBuffer.wrap(inputIdsLong), shape)
        inputs["input_ids"] = inputIdsTensor

        var attentionMaskTensor: OnnxTensor? = null
        if (declaredInputNames.contains("attention_mask")) {
            attentionMaskTensor = OnnxTensor.createTensor(env, LongBuffer.wrap(attentionMaskLong), shape)
            inputs["attention_mask"] = attentionMaskTensor
        }

        var tokenTypeIdsTensor: OnnxTensor? = null
        if (declaredInputNames.contains("token_type_ids")) {
            val tokenTypeIdsLong = LongArray(seqLen) { 0L }
            tokenTypeIdsTensor = OnnxTensor.createTensor(env, LongBuffer.wrap(tokenTypeIdsLong), shape)
            inputs["token_type_ids"] = tokenTypeIdsTensor
        }

        try {
            val result = session.run(inputs)
            try {
                // Output is last_hidden_state: [1, seqLen, 384]
                val outputTensor = result[0] as OnnxTensor
                val floatBuffer = outputTensor.floatBuffer
                val lastHiddenState = FloatArray(seqLen * EMBED_DIM)
                floatBuffer.get(lastHiddenState)

                val pooled = meanPool(lastHiddenState, attentionMaskLong, seqLen, EMBED_DIM)
                return l2Normalize(pooled)
            } finally {
                result.close()
            }
        } finally {
            inputIdsTensor.close()
            attentionMaskTensor?.close()
            tokenTypeIdsTensor?.close()
        }
    }

    override fun close() {
        session.close()
        env.close()
    }
}
