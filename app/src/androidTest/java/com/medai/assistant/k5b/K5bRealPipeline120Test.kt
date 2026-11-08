package com.medai.assistant.k5b

import androidx.test.platform.app.InstrumentationRegistry
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.gate.GateDecision
import com.medai.assistant.gate.GateSignals
import com.medai.assistant.k4d.DeviceTestRuntime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale
import kotlin.math.abs

/**
 * K5b-A: all 120 golden questions on the emulator with the real embedder.
 *
 * No exported query vector is used here: every question goes through
 * tokenize -> embedQuery (batch 1) -> dense top-3 -> gate signals -> decision.
 * Python's `assets/gate_reference.json` is the expected decision source.
 */
class K5bRealPipeline120Test {

    private data class Disagreement(
        val group: String,
        val id: Int,
        val preset: String,
        val s1: Double,
        val t1: Double,
        val s3: Double,
        val t3: Double,
        val s4: Int,
        val k: Int,
        val reason: String
    )

    @Test
    fun all120QuestionsUseTheRealOnDeviceEmbedder() {
        val rows = DeviceTestRuntime.reference
        assertEquals("gate_reference.json must contain 120 rows", 120, rows.size)
        val config = DeviceTestRuntime.config

        var balancedMatches = 0
        var strictMatches = 0
        val deltas = ArrayList<Double>(rows.size)
        val disagreements = ArrayList<Disagreement>()
        val fullCsv = StringBuilder()
        fullCsv.append(
            "group,id,question,preset,ref_s1,ref_s3,ref_s4,ref_decision," +
                "actual_s1,actual_s3,actual_s4,actual_decision,match\n"
        )

        for ((index, row) in rows.withIndex()) {
            // Exactly the app pipeline for one question: tokenize, batch-1
            // embed, dense top-3, gate signals.
            DeviceTestRuntime.tokenizer.encode(
                OnnxEmbedder.QUERY_PREFIX + row.question,
                OnnxEmbedder.MAX_LENGTH
            )
            val vector = DeviceTestRuntime.embedder.embedQuery(row.question)
            val hits = DeviceTestRuntime.denseSearch.search(vector, k = 3)
            assertTrue("DenseSearch must return at least one hit for id=${row.id}", hits.isNotEmpty())
            val signals = GateSignals.compute(
                row.question,
                hits.map { it.chunkId },
                DeviceTestRuntime.gateDatabase,
                DeviceTestRuntime.vocab
            )
            val s1 = hits.first().score.toDouble()
            deltas.add(abs(s1 - row.s1Top1))

            for (presetName in listOf("balanced", "strict")) {
                val preset = config.preset(presetName)
                val actual = GateDecision.accept(s1, signals.s3CovTop3, signals.s4Unknown, preset)
                val expected = if (presetName == "balanced") {
                    row.balancedDecision
                } else {
                    row.strictDecision
                }
                if (actual == expected) {
                    if (presetName == "balanced") balancedMatches++ else strictMatches++
                } else {
                    val reasons = ArrayList<String>()
                    if (s1 + GateDecision.EPSILON < preset.t1) reasons.add("s1<t1")
                    if (signals.s3CovTop3 + GateDecision.EPSILON < preset.t3) reasons.add("s3<t3")
                    if (signals.s4Unknown > preset.k) reasons.add("s4>k")
                    disagreements.add(
                        Disagreement(
                            group = row.group,
                            id = row.id,
                            preset = presetName,
                            s1 = s1,
                            t1 = preset.t1,
                            s3 = signals.s3CovTop3,
                            t3 = preset.t3,
                            s4 = signals.s4Unknown,
                            k = preset.k,
                            reason = reasons.joinToString("&").ifEmpty { "decision-boundary" }
                        )
                    )
                }
                fullCsv.append(
                    listOf(
                        row.group,
                        row.id.toString(),
                        csv(row.question),
                        presetName,
                        fmt(row.s1Top1),
                        fmt(row.s3CovTop3),
                        row.s4Unknown.toString(),
                        expected.toString(),
                        fmt(s1),
                        fmt(signals.s3CovTop3),
                        signals.s4Unknown.toString(),
                        actual.toString(),
                        (actual == expected).toString()
                    ).joinToString(",")
                ).append('\n')
            }

            if ((index + 1) % 20 == 0) {
                println("K5b A: ${index + 1}/${rows.size} questions embedded on device")
            }
        }

        deltas.sort()
        val maxDelta = deltas.lastOrNull() ?: 0.0
        val p95 = deltas[(deltas.size * 0.95).toInt().coerceAtMost(deltas.size - 1)]
        val mean = deltas.average()

        val summary = StringBuilder()
        summary.appendLine("K5b-A real on-device pipeline (120 questions)")
        summary.appendLine("balanced_matches=$balancedMatches/${rows.size}")
        summary.appendLine("strict_matches=$strictMatches/${rows.size}")
        summary.appendLine("pass_threshold=117/${rows.size}")
        summary.appendLine("pass=" + (balancedMatches >= 117 && strictMatches >= 117))
        summary.appendLine("abs_delta_s1_max=" + fmt(maxDelta))
        summary.appendLine("abs_delta_s1_p95=" + fmt(p95))
        summary.appendLine("abs_delta_s1_mean=" + fmt(mean))
        summary.appendLine("disagreements=${disagreements.size}")
        summary.appendLine("query_vectors_source=computed_on_emulator")
        disagreements.forEach {
            summary.appendLine(
                "DISAGREE group=${it.group} id=${it.id} preset=${it.preset} " +
                    "s1=${fmt(it.s1)} t1=${fmt(it.t1)} s3=${fmt(it.s3)} t3=${fmt(it.t3)} " +
                    "s4=${it.s4} k=${it.k} reason=${it.reason}"
            )
        }

        val context = InstrumentationRegistry.getInstrumentation().targetContext
        K5bArtifacts.writeText(context, "k5b_pipeline_120.csv", fullCsv.toString())
        K5bArtifacts.writeText(context, "k5b_pipeline_120_summary.txt", summary.toString())
        K5bArtifacts.writeText(
            context,
            "k5b_pipeline_disagreements.csv",
            buildString {
                appendLine("group,id,preset,s1,t1,s3,t3,s4,k,reason")
                disagreements.forEach {
                    appendLine(
                        "${it.group},${it.id},${it.preset},${fmt(it.s1)},${fmt(it.t1)}," +
                            "${fmt(it.s3)},${fmt(it.t3)},${it.s4},${it.k},${it.reason}"
                    )
                }
            }
        )
        K5bArtifacts.writeText(
            context,
            "k5b_pipeline_120_summary.json",
            """
            {
              "questions": ${rows.size},
              "balanced_matches": $balancedMatches,
              "strict_matches": $strictMatches,
              "pass_threshold": 117,
              "s1_delta_max": $maxDelta,
              "s1_delta_p95": $p95,
              "s1_delta_mean": $mean,
              "disagreements": ${disagreements.size}
            }
            """.trimIndent() + "\n"
        )

        println(summary)
        assertTrue(
            "K5b-A balanced decisions $balancedMatches/${rows.size} must be >= 117",
            balancedMatches >= 117
        )
        assertTrue(
            "K5b-A strict decisions $strictMatches/${rows.size} must be >= 117",
            strictMatches >= 117
        )
    }

    private fun fmt(value: Double): String =
        String.format(Locale.ROOT, "%.6f", value)

    private fun csv(value: String): String {
        return "\"" + value.replace("\"", "\"\"") + "\""
    }
}
