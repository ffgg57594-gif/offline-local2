package com.medai.assistant.embedder

import com.medai.assistant.tokenizer.Tokenizer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sqrt

class OnnxEmbedderTest {

    @Test
    fun testMeanPoolingAndL2NormalizationPureFunctions() {
        // Simple 2-token sequence, dim=3
        // Token 0: [2.0, 4.0, 6.0], mask=1
        // Token 1: [100.0, 200.0, 300.0], mask=0 (padding)
        val lastHiddenState = floatArrayOf(
            2.0f, 4.0f, 6.0f,
            100.0f, 200.0f, 300.0f
        )
        val attentionMask = longArrayOf(1L, 0L)
        val pooled = OnnxEmbedder.meanPool(lastHiddenState, attentionMask, seqLen = 2, dim = 3)

        assertEquals(3, pooled.size)
        assertEquals(2.0f, pooled[0], 1e-5f)
        assertEquals(4.0f, pooled[1], 1e-5f)
        assertEquals(6.0f, pooled[2], 1e-5f)

        val normalized = OnnxEmbedder.l2Normalize(pooled)
        val norm = sqrt(
            (normalized[0] * normalized[0] +
             normalized[1] * normalized[1] +
             normalized[2] * normalized[2]).toDouble()
        ).toFloat()
        assertEquals(1.0f, norm, 1e-5f)

        // Expected direction
        val expectedNorm = sqrt((2 * 2 + 4 * 4 + 6 * 6).toDouble()).toFloat()
        assertEquals(2.0f / expectedNorm, normalized[0], 1e-5f)
        assertEquals(4.0f / expectedNorm, normalized[1], 1e-5f)
        assertEquals(6.0f / expectedNorm, normalized[2], 1e-5f)
    }

    @Test
    fun testEmbedderParityAgainstReferenceJson() {
        val modelFile = sequenceOf(
            File("src/main/assets/models/embedder/model_quantized.onnx"),
            File("app/src/main/assets/models/embedder/model_quantized.onnx"),
            File("../app/src/main/assets/models/embedder/model_quantized.onnx"),
            File("assets/models/embedder/model_quantized.onnx")
        ).firstOrNull { it.exists() }

        val tokenizerBinFile = sequenceOf(
            File("src/main/assets/models/embedder/tokenizer.bin"),
            File("app/src/main/assets/models/embedder/tokenizer.bin"),
            File("../app/src/main/assets/models/embedder/tokenizer.bin"),
            File("assets/models/embedder/tokenizer.bin")
        ).firstOrNull { it.exists() }

        val refFile = sequenceOf(
            File("src/main/assets/embedder_reference.json"),
            File("app/src/main/assets/embedder_reference.json"),
            File("../app/src/main/assets/embedder_reference.json"),
            File("assets/embedder_reference.json")
        ).firstOrNull { it.exists() }

        if (modelFile == null || tokenizerBinFile == null || refFile == null) {
            println("Skipping testEmbedderParityAgainstReferenceJson: required files missing (model: $modelFile, tokenizer: $tokenizerBinFile, ref: $refFile)")
            return
        }

        val tokenizer = Tokenizer.fromBinaryFile(tokenizerBinFile)
        val embedder = OnnxEmbedder(modelFile, tokenizer)

        val content = refFile.readText(Charsets.UTF_8)
        // Parse simple JSON array without third party json lib
        val entries = parseEmbedderReference(content)
        println("Testing embedder parity across ${entries.size} reference vectors...")

        println("\n=========================================================================================")
        println("EMBEDDER REFERENCE PARITY TABLE (24 Reference Vectors)")
        println("=========================================================================================")
        println(String.format("%-4s | %-8s | %-12s | %-50s", "ID", "Kind", "Cosine", "Input (truncated)"))
        println("-----+----------+--------------+---------------------------------------------------------")

        var minCosine = 1.0f
        for (entry in entries) {
            // Note: reference vectors in embedder_reference.json are generated with:
            // if kind == "passage": prefix = "passage: "
            // if kind == "query": prefix = "query: "
            // The prompt states:
            // Query text = "query: " + question, tokenizer truncation 384
            // Let's test using embedQuery for query kind, and prefix appropriately
            val text = if (entry.kind == "query") {
                entry.input
            } else {
                // If passage, test with raw input prepended as passage
                // For direct testing, embedder.embedQuery prepends "query: "
                // To test both kinds with embedQuery logic:
                entry.input
            }

            // In embedder_reference.json:
            // "query: " + input was passed to embedder for kind="query",
            // "passage: " + input was passed for kind="passage".
            // If entry.kind == "query", embedQuery(entry.input) produces the exact same text ("query: " + entry.input).
            // If entry.kind == "passage", we test query embedder or test with "passage: "
            val computedVec = if (entry.kind == "query") {
                embedder.embedQuery(entry.input)
            } else {
                // Encode with "passage: " prefix to verify underlying ONNX inference parity on passages too
                val enc = tokenizer.encode("passage: " + entry.input, OnnxEmbedder.MAX_LENGTH)
                val seqLen = enc.ids.size
                val inputIds = LongArray(seqLen) { i -> enc.ids[i].toLong() }
                val mask = LongArray(seqLen) { 1L }
                val shape = longArrayOf(1L, seqLen.toLong())
                val env = ai.onnxruntime.OrtEnvironment.getEnvironment()
                val tIds = ai.onnxruntime.OnnxTensor.createTensor(env, java.nio.LongBuffer.wrap(inputIds), shape)
                val tMask = ai.onnxruntime.OnnxTensor.createTensor(env, java.nio.LongBuffer.wrap(mask), shape)
                val tTypes = ai.onnxruntime.OnnxTensor.createTensor(env, java.nio.LongBuffer.wrap(LongArray(seqLen)), shape)
                val map = mapOf("input_ids" to tIds, "attention_mask" to tMask, "token_type_ids" to tTypes)
                // Use reflection or private session if needed, or instantiate session
                val sessField = OnnxEmbedder::class.java.getDeclaredField("session")
                sessField.isAccessible = true
                val sess = sessField.get(embedder) as ai.onnxruntime.OrtSession
                val res = sess.run(map)
                val out = res[0] as ai.onnxruntime.OnnxTensor
                val lastHidden = FloatArray(seqLen * OnnxEmbedder.EMBED_DIM)
                out.floatBuffer.get(lastHidden)
                res.close()
                tIds.close()
                tMask.close()
                tTypes.close()
                val pooled = OnnxEmbedder.meanPool(lastHidden, mask, seqLen, OnnxEmbedder.EMBED_DIM)
                OnnxEmbedder.l2Normalize(pooled)
            }

            val cosine = OnnxEmbedder.cosineSimilarity(computedVec, entry.vector)
            if (cosine < minCosine) minCosine = cosine

            val displayInput = if (entry.input.length > 50) entry.input.substring(0, 47) + "..." else entry.input
            println(String.format("%-4d | %-8s | %12.6f | %-50s", entry.id, entry.kind, cosine, displayInput))

            assertTrue("Cosine similarity for vector #${entry.id} ($cosine) must be >= 0.998", cosine >= 0.998f)
        }
        println("=========================================================================================")
        println("Embedder parity test passed! Minimum cosine similarity: $minCosine (target >= 0.998)\n")

        embedder.close()
    }

    data class RefEntry(
        val id: Int,
        val kind: String,
        val input: String,
        val vector: FloatArray
    )

    private fun parseEmbedderReference(jsonStr: String): List<RefEntry> {
        val entries = mutableListOf<RefEntry>()
        val entriesPos = jsonStr.indexOf("\"entries\"")
        val searchStart = if (entriesPos != -1) entriesPos else 0
        var startIdx = jsonStr.indexOf('{', searchStart)
        while (startIdx != -1) {
            var depth = 0
            var endIdx = -1
            var inStr = false
            var escape = false
            for (i in startIdx until jsonStr.length) {
                val c = jsonStr[i]
                if (escape) {
                    escape = false
                    continue
                }
                if (c == '\\') {
                    escape = true
                    continue
                }
                if (c == '"') {
                    inStr = !inStr
                    continue
                }
                if (!inStr) {
                    if (c == '{') depth++
                    else if (c == '}') {
                        depth--
                        if (depth == 0) {
                            endIdx = i
                            break
                        }
                    }
                }
            }
            if (endIdx == -1) break

            val objStr = jsonStr.substring(startIdx, endIdx + 1)
            val id = extractInt(objStr, "id")
            val kind = extractString(objStr, "kind")
            val input = extractString(objStr, "input")
            val vector = extractFloatArray(objStr, "vector")

            if (id > 0 && vector.isNotEmpty()) {
                entries.add(RefEntry(id, kind, input, vector))
            }
            startIdx = jsonStr.indexOf('{', endIdx + 1)
        }
        return entries
    }

    private fun extractInt(objStr: String, key: String): Int {
        val k = "\"$key\":"
        val pos = objStr.indexOf(k)
        if (pos == -1) return 0
        var start = pos + k.length
        while (start < objStr.length && (objStr[start] == ' ' || objStr[start] == '\t')) start++
        var end = start
        while (end < objStr.length && (objStr[end].isDigit() || objStr[end] == '-')) end++
        return objStr.substring(start, end).toIntOrNull() ?: 0
    }

    private fun extractString(objStr: String, key: String): String {
        val k = "\"$key\":"
        val pos = objStr.indexOf(k)
        if (pos == -1) return ""
        val quoteStart = objStr.indexOf('"', pos + k.length)
        if (quoteStart == -1) return ""
        val sb = StringBuilder()
        var i = quoteStart + 1
        var escape = false
        while (i < objStr.length) {
            val c = objStr[i]
            if (escape) {
                when (c) {
                    'n' -> sb.append('\n')
                    'r' -> sb.append('\r')
                    't' -> sb.append('\t')
                    '\\' -> sb.append('\\')
                    '"' -> sb.append('"')
                    'u' -> {
                        val hex = objStr.substring(i + 1, min(i + 5, objStr.length))
                        sb.append(hex.toInt(16).toChar())
                        i += 4
                    }
                    else -> sb.append(c)
                }
                escape = false
            } else if (c == '\\') {
                escape = true
            } else if (c == '"') {
                break
            } else {
                sb.append(c)
            }
            i++
        }
        return sb.toString()
    }

    private fun extractFloatArray(objStr: String, key: String): FloatArray {
        val k = "\"$key\":"
        val pos = objStr.indexOf(k)
        if (pos == -1) return FloatArray(0)
        val arrStart = objStr.indexOf('[', pos + k.length)
        val arrEnd = objStr.indexOf(']', arrStart)
        if (arrStart == -1 || arrEnd == -1) return FloatArray(0)
        val elements = objStr.substring(arrStart + 1, arrEnd).split(',')
        val result = FloatArray(elements.size)
        for (i in elements.indices) {
            result[i] = elements[i].trim().toFloatOrNull() ?: 0f
        }
        return result
    }
}
