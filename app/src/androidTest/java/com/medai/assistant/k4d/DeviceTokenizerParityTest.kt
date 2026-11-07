package com.medai.assistant.k4d

import com.medai.assistant.tokenizer.Tokenizer
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * K4d: the exact 416-case reference file is run through the on-device
 * tokenizer (binary SentencePiece asset) instead of only on the JVM.
 */
class DeviceTokenizerParityTest {

    @Test
    fun testAllReferenceCasesMatchOnDevice() {
        val cases = DeviceReferenceParsers.parseTokenizerReference(
            DeviceTestRuntime.testAssetText("tokenizer_reference.json")
        )
        assertEquals("tokenizer_reference.json must contain 416 cases", 416, cases.size)

        var passed = 0
        val mismatches = ArrayList<String>()
        for (case in cases) {
            val encoding = DeviceTestRuntime.tokenizer.encode(case.input, Tokenizer.MAX_LENGTH)
            val idMatch = encoding.ids == case.ids
            val attentionMatch = encoding.attentionLength == case.expectedAttentionLength
            if (idMatch && attentionMatch) {
                passed++
            } else {
                mismatches.add(
                    "case #${case.id} [${case.category}] firstDiff=${firstDiff(case.ids, encoding.ids)} " +
                        "expectedLen=${case.ids.size} actualLen=${encoding.ids.size} " +
                        "expectedAttention=${case.expectedAttentionLength} " +
                        "actualAttention=${encoding.attentionLength}"
                )
            }
        }

        println("K4d tokenizer parity: $passed/${cases.size} cases")
        if (mismatches.isNotEmpty()) {
            mismatches.take(20).forEach { println("  $it") }
        }
        assertEquals(
            "All ${cases.size} tokenizer reference cases must match on device",
            cases.size,
            passed
        )
    }

    private fun firstDiff(expected: List<Int>, actual: List<Int>): Int {
        val minLen = minOf(expected.size, actual.size)
        for (i in 0 until minLen) {
            if (expected[i] != actual[i]) return i
        }
        return minLen
    }
}
