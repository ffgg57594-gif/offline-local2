package com.medai.assistant.tokenizer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import java.io.File
import java.io.FileInputStream

class TokenizerTest {

    companion object {
        private var tokenizer: Tokenizer? = null
        private var loadTimeMs: Long = 0
        private var peakHeapBytes: Long = 0

        @BeforeClass
        @JvmStatic
        fun setUp() {
            val runtime = Runtime.getRuntime()
            runtime.gc()
            val beforeMem = runtime.totalMemory() - runtime.freeMemory()

            val tokenizerFile = sequenceOf(
                File("src/main/assets/models/embedder/tokenizer.json"),
                File("app/src/main/assets/models/embedder/tokenizer.json"),
                File("../app/src/main/assets/models/embedder/tokenizer.json")
            ).firstOrNull { it.exists() }

            if (tokenizerFile == null) {
                println("tokenizer.json not found on disk; skipping tokenizer initialization")
                return
            }

            val t0 = System.currentTimeMillis()
            FileInputStream(tokenizerFile).use { fis ->
                tokenizer = Tokenizer.fromStream(fis)
            }
            loadTimeMs = System.currentTimeMillis() - t0

            runtime.gc()
            val afterMem = runtime.totalMemory() - runtime.freeMemory()
            peakHeapBytes = (afterMem - beforeMem).coerceAtLeast(0)

            println("\n=======================================================")
            println("INFORMATIONAL: Tokenizer Performance Benchmark")
            println("Tokenizer load time : $loadTimeMs ms")
            println("Tokenizer peak heap : ${peakHeapBytes / (1024 * 1024)} MB (${peakHeapBytes} bytes)")
            println("=======================================================\n")
        }
    }

    @Test
    fun testSmallHandMadeVocabulary() {
        // Small unit test of components with hand-made vocabulary
        val vocab = listOf(
            Pair("<s>", 0.0),
            Pair("<pad>", 0.0),
            Pair("</s>", 0.0),
            Pair("<unk>", 0.0),
            Pair("▁", -1.0),
            Pair("a", -2.0),
            Pair("b", -2.0),
            Pair("c", -2.0),
            Pair("▁ab", -1.5),
            Pair("bc", -1.5)
        )
        // Construct json structure string in memory
        val json = buildString {
            append("{\n")
            append("  \"model\": {\n")
            append("    \"type\": \"Unigram\",\n")
            append("    \"unk_id\": 3,\n")
            append("    \"vocab\": [\n")
            vocab.forEachIndexed { i, p ->
                append("      [\n")
                append("        \"${p.first}\",\n")
                append("        ${p.second}\n")
                if (i < vocab.size - 1) append("      ],\n") else append("      ]\n")
            }
            append("    ]\n")
            append("  }\n")
            append("}\n")
        }

        val miniTok = Tokenizer.fromStream(json.byteInputStream())
        // "ab" should segment into ["ab"] because score(-1.5) > score(a) + score(b) = -4.0
        val res = miniTok.encode("ab")
        assertEquals(listOf(0, 8, 2), res.ids)
        assertEquals(listOf("<s>", "▁ab", "</s>"), res.tokens)
    }

    @Test
    fun testReferenceParityCases() {
        // Look in classpath first, then relative paths
        val refStream = TokenizerTest::class.java.classLoader?.getResourceAsStream("tokenizer_reference.json")
            ?: File("src/test/resources/tokenizer_reference.json").takeIf { it.exists() }?.inputStream()
            ?: File("app/src/test/resources/tokenizer_reference.json").takeIf { it.exists() }?.inputStream()

        if (refStream == null) {
            println("tokenizer_reference.json not found on CI runner (not checked into git). Skipping reference parity check.")
            return
        }

        val tok = tokenizer ?: error("Tokenizer not initialized")

        // Parse reference cases
        val content = refStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        val jsonArrayStart = content.indexOf("\"cases\": [")
        assertTrue(jsonArrayStart != -1)

        val cases = parseReferenceCases(content)
        assertTrue("At least 400 reference cases present", cases.size >= 400)

        val categoryStats = LinkedHashMap<String, IntArray>() // [passed, total]
        val mismatches = ArrayList<String>()

        for (case in cases) {
            val stats = categoryStats.getOrPut(case.category) { IntArray(2) }
            stats[1]++ // total

            val encoding = tok.encode(case.input, Tokenizer.MAX_LENGTH)
            val actualIds = encoding.ids
            val expectedIds = case.ids

            val actualAttLen = encoding.attentionLength
            val expectedAttLen = case.expectedAttentionLength

            val idMatch = (actualIds == expectedIds)
            val attMatch = (actualAttLen == expectedAttLen)

            if (idMatch && attMatch) {
                stats[0]++ // passed
            } else {
                val firstDiff = findFirstDiff(expectedIds, actualIds)
                val msg = buildString {
                    append("Mismatch in Case #${case.id} [${case.category}]:\n")
                    append("  Input      : ${case.input.take(80)}\n")
                    append("  First Diff : index $firstDiff\n")
                    append("  Expected   : ${expectedIds.take(15)} (len ${expectedIds.size})\n")
                    append("  Actual     : ${actualIds.take(15)} (len ${actualIds.size})\n")
                }
                mismatches.add(msg)
                System.err.println(msg)
            }
        }

        // Print full parity table
        println("\n=========================================================================")
        println("TOKENIZER REFERENCE PARITY REPORT")
        println("=========================================================================")
        println(String.format("%-32s | %-10s | %-10s | %-10s", "Category", "Passed", "Total", "Pass Rate"))
        println("---------------------------------+------------+------------+-------------")
        var totalPassed = 0
        var grandTotal = 0
        for ((cat, counts) in categoryStats) {
            val passed = counts[0]
            val total = counts[1]
            totalPassed += passed
            grandTotal += total
            val pct = (passed * 100.0) / total
            println(String.format("%-32s | %10d | %10d | %9.1f%%", cat, passed, total, pct))
        }
        println("---------------------------------+------------+------------+-------------")
        val grandPct = (totalPassed * 100.0) / grandTotal
        println(String.format("%-32s | %10d | %10d | %9.1f%%", "TOTAL", totalPassed, grandTotal, grandPct))
        println("=========================================================================\n")

        if (mismatches.isNotEmpty()) {
            println("Total mismatches: ${mismatches.size} / $grandTotal")
            for (m in mismatches.take(20)) {
                println(m)
            }
        }

        assertEquals("All reference cases must match with 100% parity", grandTotal, totalPassed)
    }

    private fun findFirstDiff(expected: List<Int>, actual: List<Int>): Int {
        val minLen = minOf(expected.size, actual.size)
        for (i in 0 until minLen) {
            if (expected[i] != actual[i]) return i
        }
        return minLen
    }

    private data class RefCase(
        val id: Int,
        val category: String,
        val input: String,
        val ids: List<Int>,
        val expectedAttentionLength: Int
    )

    private fun parseReferenceCases(jsonText: String): List<RefCase> {
        val cases = ArrayList<RefCase>()
        val marker = "\"cases\": ["
        val startIdx = jsonText.indexOf(marker)
        if (startIdx == -1) return cases

        val arrayContent = jsonText.substring(startIdx + marker.length)
        var pos = 0

        while (pos < arrayContent.length) {
            val objStart = arrayContent.indexOf('{', pos)
            if (objStart == -1) break
            var depth = 0
            var inStr = false
            var escape = false
            var objEnd = -1

            for (i in objStart until arrayContent.length) {
                val c = arrayContent[i]
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
                            objEnd = i
                            break
                        }
                    }
                }
            }

            if (objEnd == -1) break
            val objJson = arrayContent.substring(objStart, objEnd + 1)
            pos = objEnd + 1

            // Parse fields of this case
            val id = extractInt(objJson, "\"id\":")
            val cat = extractString(objJson, "\"category\":")
            val input = extractString(objJson, "\"input\":")
            val ids = extractIntList(objJson, "\"ids\":")
            val attLen = extractInt(objJson, "\"expected_attention_length\":")

            cases.add(RefCase(id, cat, input, ids, attLen))
        }

        return cases
    }

    private fun extractInt(json: String, key: String): Int {
        val idx = json.indexOf(key)
        if (idx == -1) return 0
        val start = idx + key.length
        val end = json.indexOfAny(charArrayOf(',', '\n', '}'), start)
        val numStr = json.substring(start, if (end != -1) end else json.length).trim()
        return numStr.toIntOrNull() ?: 0
    }

    private fun extractString(json: String, key: String): String {
        val idx = json.indexOf(key)
        if (idx == -1) return ""
        val quote1 = json.indexOf('"', idx + key.length)
        if (quote1 == -1) return ""
        var quote2 = quote1 + 1
        var escape = false
        while (quote2 < json.length) {
            val c = json[quote2]
            if (escape) {
                escape = false
            } else if (c == '\\') {
                escape = true
            } else if (c == '"') {
                break
            }
            quote2++
        }
        val raw = json.substring(quote1 + 1, quote2)
        return raw.replace("\\\"", "\"")
            .replace("\\\\", "\\")
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
    }

    private fun extractIntList(json: String, key: String): List<Int> {
        val idx = json.indexOf(key)
        if (idx == -1) return emptyList()
        val bracket1 = json.indexOf('[', idx + key.length)
        val bracket2 = json.indexOf(']', bracket1)
        if (bracket1 == -1 || bracket2 == -1) return emptyList()
        val listStr = json.substring(bracket1 + 1, bracket2).trim()
        if (listStr.isEmpty()) return emptyList()
        return listStr.split(',').mapNotNull { it.trim().toIntOrNull() }
    }
}
