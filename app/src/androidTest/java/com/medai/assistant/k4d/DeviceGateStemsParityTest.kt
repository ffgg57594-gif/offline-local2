package com.medai.assistant.k4d

import com.medai.assistant.gate.GateSignals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale

/**
 * K4d: on the emulator, feed the Python top-3 chunk ids into the Android FTS5
 * stemmer and require exact s3/s4 parity with gate_reference.json (120/120).
 */
class DeviceGateStemsParityTest {

    @Test
    fun testS3AndS4MatchPythonReferenceUsingPythonTop3() {
        val reference = DeviceTestRuntime.reference
        assertEquals("gate_reference.json must contain 120 rows", 120, reference.size)

        val csvRows = DeviceReferenceParsers.parseCsv(
            DeviceTestRuntime.testAssetText("retrieval_top5.csv")
        )
        val csvByGroupId = csvRows.associateBy {
            "${it["group"]}|${it["id"]?.toIntOrNull() ?: -1}"
        }

        val differences = mutableListOf<String>()
        for (row in reference) {
            val csv = csvByGroupId["${row.group}|${row.id}"]
                ?: error("retrieval_top5.csv has no row for group=${row.group} id=${row.id}")
            val top3 = listOf("rank_1_chunk_id", "rank_2_chunk_id", "rank_3_chunk_id")
                .map { key ->
                    csv[key]?.toIntOrNull()
                        ?: error("missing $key for group=${row.group} id=${row.id}")
                }
            val signals = GateSignals.compute(
                row.question,
                top3,
                DeviceTestRuntime.gateDatabase,
                DeviceTestRuntime.vocab
            )

            val androidS3 = String.format(Locale.ROOT, "%.6f", signals.s3CovTop3)
            val pythonS3 = String.format(Locale.ROOT, "%.6f", row.s3CovTop3)
            if (androidS3 != pythonS3 || signals.s4Unknown != row.s4Unknown) {
                differences.add(
                    "group=${row.group} id=${row.id} android_s3=$androidS3 python_s3=$pythonS3 " +
                        "android_s4=${signals.s4Unknown} python_s4=${row.s4Unknown} " +
                        "stems=[${signals.stems.joinToString(" ")}] top3=[${top3.joinToString(",")}]"
                )
            }
        }

        if (differences.isEmpty()) {
            println("K4d gate stems/s3/s4: ${reference.size}/${reference.size} exact matches")
        } else {
            println("K4d gate stems/s3/s4 differences=${differences.size}")
            differences.forEach { println("  $it") }
        }
        assertTrue(
            "K4d s3/s4 must match gate_reference.json exactly; differences=${differences.size}: " +
                differences.joinToString(" || "),
            differences.isEmpty()
        )
    }
}
