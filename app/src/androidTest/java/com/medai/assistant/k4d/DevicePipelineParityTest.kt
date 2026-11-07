package com.medai.assistant.k4d

import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.gate.GateDecision
import com.medai.assistant.gate.GateSignals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

/**
 * K4d: full dense-retrieval -> refusal-gate pipeline on the emulator.
 *
 * The query vectors are the exact Python vectors that produced
 * `gate_reference.json` (exported by `scripts/measure_gate_signals.py` and
 * staged into the instrumented-test APK). Replaying them through the Android
 * DenseSearch + FTS5 gate isolates the ranking/gating port, which must match
 * the Python s1 within 1e-3 and both preset decisions 120/120.
 *
 * On-device embedding is covered separately by [DeviceEmbedderParityTest]
 * (24 reference vectors, cosine >= 0.997). onnxruntime-android and the Linux
 * Python wheel use different CPU kernels for the quantised model, so their
 * query vectors differ slightly; that difference belongs to the embedder test,
 * not to the deterministic ranking/gating test.
 */
class DevicePipelineParityTest {

    private val s1Tolerance = 1e-3

    @Test
    fun testFullPipelineDecisionsMatchReferenceOnDevice() {
        val reference = DeviceTestRuntime.reference
        assertEquals("gate_reference.json must contain 120 rows", 120, reference.size)

        val vectors = DeviceReferenceParsers.parseCsv(
            DeviceTestRuntime.testAssetText("gate_query_vectors.csv")
        ).associateBy { "${it["group"]}|${it["id"]}" }
        assertEquals(
            "gate_query_vectors.csv must contain one vector per reference row",
            reference.size,
            vectors.size
        )

        var balancedMatches = 0
        var strictMatches = 0
        var maxS1Delta = 0.0
        val disagreements = mutableListOf<String>()

        for ((index, row) in reference.withIndex()) {
            val raw = vectors["${row.group}|${row.id}"]
                ?: error("gate_query_vectors.csv has no vector for group=${row.group} id=${row.id}")
            val queryVector = FloatArray(OnnxEmbedder.EMBED_DIM) { dim ->
                raw["v$dim"]?.toFloatOrNull()
                    ?: error("missing v$dim for group=${row.group} id=${row.id}")
            }

            val hits = DeviceTestRuntime.denseSearch.search(queryVector, k = 3)
            assertTrue("DenseSearch must return at least one hit", hits.isNotEmpty())
            val s1 = hits[0].score.toDouble()
            val delta = abs(s1 - row.s1Top1)
            if (delta > maxS1Delta) maxS1Delta = delta

            val signals = GateSignals.compute(
                row.question,
                hits.map { it.chunkId },
                DeviceTestRuntime.gateDatabase,
                DeviceTestRuntime.vocab
            )

            val balanced = GateDecision.accept(
                s1,
                signals.s3CovTop3,
                signals.s4Unknown,
                DeviceTestRuntime.config.balanced
            )
            val strict = GateDecision.accept(
                s1,
                signals.s3CovTop3,
                signals.s4Unknown,
                DeviceTestRuntime.config.strict
            )

            if (balanced == row.balancedDecision) balancedMatches++ else disagreements.add(
                "balanced group=${row.group} id=${row.id} reference=${row.balancedDecision} " +
                    "device=$balanced s1=$s1 refS1=${row.s1Top1} " +
                    "s3=${signals.s3CovTop3} refS3=${row.s3CovTop3} s4=${signals.s4Unknown}"
            )
            if (strict == row.strictDecision) strictMatches++ else disagreements.add(
                "strict group=${row.group} id=${row.id} reference=${row.strictDecision} " +
                    "device=$strict s1=$s1 refS1=${row.s1Top1} " +
                    "s3=${signals.s3CovTop3} refS3=${row.s3CovTop3} s4=${signals.s4Unknown}"
            )

            if ((index + 1) % 20 == 0) {
                println("K4d pipeline: ${index + 1}/${reference.size} questions")
            }
        }

        println(
            "K4d pipeline: max |s1_device - s1_reference|=$maxS1Delta " +
                "(tolerance $s1Tolerance); balanced=$balancedMatches/${reference.size}; " +
                "strict=$strictMatches/${reference.size}"
        )
        if (disagreements.isNotEmpty()) {
            disagreements.take(20).forEach { println("  $it") }
        }

        assertTrue(
            "K4d max |s1_device - s1_reference| $maxS1Delta must be <= $s1Tolerance",
            maxS1Delta <= s1Tolerance
        )
        assertEquals(
            "K4d balanced decisions must match ${reference.size}/${reference.size}",
            reference.size,
            balancedMatches
        )
        assertEquals(
            "K4d strict decisions must match ${reference.size}/${reference.size}",
            reference.size,
            strictMatches
        )
    }
}
