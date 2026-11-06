package com.medai.assistant.embedder

import com.medai.assistant.tokenizer.Tokenizer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
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
            println("Skipping testEmbedderParityAgainstReferenceJson: required files missing")
            return
        }

        val tokenizer = Tokenizer.fromBinaryFile(tokenizerBinFile)
        val embedder = OnnxEmbedder(modelFile, tokenizer)

        val content = refFile.readText(Charsets.UTF_8)
        val entries = parseEmbedderReference(content)
        println("Testing embedder parity across ${entries.size} reference vectors...")

        // Prepare report file: build/reports/parity/embedder_parity.csv
        val reportDir = File("build/reports/parity").takeIf { it.isAbsolute }
            ?: (if (File("app").exists()) File("build/reports/parity") else File("../build/reports/parity"))
        reportDir.mkdirs()
        val reportFile = File(reportDir, "embedder_parity.csv")
        val csvLines = mutableListOf<String>()
        csvLines.add("index,kind,input,cosine")

        var minCosine = 1.0f
        for (entry in entries) {
            val computedVec = if (entry.kind == "query") {
                embedder.embedQuery(entry.input)
            } else {
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

            // Truncate to 80 chars
            val truncatedInput = if (entry.input.length > 80) entry.input.substring(0, 80) else entry.input
            val safeInput = "\"" + truncatedInput.replace("\"", "\"\"").replace("\n", " ") + "\""
            csvLines.add("${entry.id},${entry.kind},$safeInput,${String.format("%.6f", cosine)}")

            assertTrue("Cosine similarity for vector #${entry.id} ($cosine) must be >= 0.998", cosine >= 0.998f)
        }

        reportFile.writeText(csvLines.joinToString("\n") + "\n", Charsets.UTF_8)
        println("Wrote embedder parity report to ${reportFile.absolutePath} (${entries.size} rows)")

        // Also write to project root if run from subproject
        val rootReport = File("build/reports/parity/embedder_parity.csv")
        if (rootReport.canonicalPath != reportFile.canonicalPath) {
            rootReport.parentFile?.mkdirs()
            rootReport.writeText(csvLines.joinToString("\n") + "\n", Charsets.UTF_8)
        }

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
            parseRefEntry(objStr)?.let { entries.add(it) }
            startIdx = jsonStr.indexOf('{', endIdx + 1)
        }
        return entries
    }

    private fun parseRefEntry(objStr: String): RefEntry? {
        val idVal = extractJsonInt(objStr, "id") ?: return null
        val kindVal = extractJsonString(objStr, "kind") ?: return null
        val inputVal = extractJsonString(objStr, "input") ?: return null
        val vectorVal = extractJsonFloatArray(objStr, "vector") ?: return null
        return RefEntry(idVal, kindVal, inputVal, vectorVal)
    }

    private fun extractJsonInt(json: String, key: String): Int? {
        val pattern = "\"$key\"\\s*:\\s*(\\d+)".toRegex()
        return pattern.find(json)?.groupValues?.get(1)?.toIntOrNull()
    }

    private fun extractJsonString(json: String, key: String): String? {
        val k = "\"$key\""
        val idx = json.indexOf(k)
        if (idx == -1) return null
        val colon = json.indexOf(':', idx + k.length)
        if (colon == -1) return null
        val startQuote = json.indexOf('"', colon + 1)
        if (startQuote == -1) return null
        val sb = StringBuilder()
        var escape = false
        var i = startQuote + 1
        while (i < json.length) {
            val c = json[i]
            if (escape) {
                when (c) {
                    '"' -> sb.append('"')
                    '\\' -> sb.append('\\')
                    'n' -> sb.append('\n')
                    'r' -> sb.append('\r')
                    't' -> sb.append('\t')
                    'u' -> {
                        if (i + 4 < json.length) {
                            val hex = json.substring(i + 1, i + 5)
                            val codePoint = hex.toIntOrNull(16)
                            if (codePoint != null) {
                                sb.append(codePoint.toChar())
                                i += 4
                            }
                        }
                    }
                    else -> sb.append(c)
                }
                escape = false
            } else if (c == '\\') {
                escape = true
            } else if (c == '"') {
                return sb.toString()
            } else {
                sb.append(c)
            }
            i++
        }
        return null
    }

    private fun extractJsonFloatArray(json: String, key: String): FloatArray? {
        val k = "\"$key\""
        val idx = json.indexOf(k)
        if (idx == -1) return null
        val startBracket = json.indexOf('[', idx + k.length)
        if (startBracket == -1) return null
        val endBracket = json.indexOf(']', startBracket)
        if (endBracket == -1) return null
        val inner = json.substring(startBracket + 1, endBracket)
        val tokens = inner.split(',')
        val arr = FloatArray(tokens.size)
        for (i in tokens.indices) {
            arr[i] = tokens[i].trim().toFloatOrNull() ?: 0.0f
        }
        return arr
    }
}
