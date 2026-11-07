package com.medai.assistant.gate

import com.medai.assistant.data.JdbcChunkRepository
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.search.DenseSearch
import com.medai.assistant.tokenizer.Tokenizer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.Locale
import kotlin.math.abs

/**
 * K4c test (b): run the full Kotlin embedder + DenseSearch + gate-signal
 * pipeline on all 120 questions and compare its balanced/strict decisions with
 * `gate_reference.json`.
 *
 * Acceptance requirements:
 *  - max |s1_python - s1_kotlin| <= 1e-4 for all 120 questions;
 *  - 120/120 decisions equal per preset;
 *  - question IN 14 has s3 = 4/7 and the same decision in Python and Kotlin.
 */
class GateDecisionParityTest {

    private data class Disagreement(
        val preset: String,
        val cls: String,
        val id: Int,
        val question: String,
        val pythonDecision: Boolean,
        val kotlinDecision: Boolean,
        val s1: Double,
        val t1: Double,
        val absS1T1: Double,
        val s3: Double,
        val s3Python: Double,
        val t3: Double,
        val s4: Int,
        val reason: String
    )

    private val s1Epsilon = 1e-4
    private val minDecisionMatches = 120

    @Test
    fun testFullPipelineDecisionsMatchPythonReference() {
        val vocab = GateVocab.load(GateTestAssets.vocab)
        val config = GateConfig.load(GateTestAssets.config)
        val reference = GateReference.load(GateTestAssets.reference)
        val tokenizer = Tokenizer.fromBinaryFile(GateTestAssets.tokenizerBin)
        val embedder = OnnxEmbedder(GateTestAssets.model, tokenizer)
        val repository = JdbcChunkRepository(GateTestAssets.database)
        val pages = repository.getAllPages(1185)
        val denseSearch = DenseSearch(GateTestAssets.embeddings, 1185, 384, pages)

        val presets: List<Triple<String, GatePreset, (GateReferenceRow) -> Boolean>> = listOf(
            Triple("balanced", config.balanced, { row: GateReferenceRow -> row.balancedDecision }),
            Triple("strict", config.strict, { row: GateReferenceRow -> row.strictDecision })
        )

        val allRows = mutableListOf<String>()
        allRows.add(
            "preset,cls,id,question,python_decision,kotlin_decision,agree," +
                "s1_kotlin,s1_python,t1,abs_s1_minus_t1,s3_kotlin,s3_python,t3,s4_kotlin,s4_python,k,reason"
        )
        val disagreements = mutableListOf<Disagreement>()
        var maxS1Delta = 0.0
        var s1DeltaRows = 0

        var in14Row: GateReferenceRow? = null
        var in14S3 = Double.NaN
        val in14Decisions = mutableMapOf<String, Pair<Boolean, Boolean>>()

        JdbcGateDatabase(GateTestAssets.database).use { database ->
            for (row in reference) {
                val queryVector = embedder.embedQuery(row.question)
                val hits = denseSearch.search(queryVector, k = 3)
                val s1 = hits[0].score.toDouble()
                val signals = GateSignals.compute(
                    row.question,
                    hits.map { it.chunkId },
                    database,
                    vocab
                )

                val s1Delta = abs(s1 - row.s1Top1)
                maxS1Delta = maxOf(maxS1Delta, s1Delta)
                s1DeltaRows++

                if (row.cls == "IN" && row.id == 14) {
                    in14Row = row
                    in14S3 = signals.s3CovTop3
                }

                for ((presetName, preset, pythonDecisionGetter) in presets) {
                    val pythonDecision = pythonDecisionGetter(row)
                    val kotlinDecision = GateDecision.accept(
                        s1,
                        signals.s3CovTop3,
                        signals.s4Unknown,
                        preset
                    )
                    val absS1T1 = abs(s1 - preset.t1)
                    val reason = buildReason(
                        presetName,
                        preset,
                        s1,
                        signals.s3CovTop3,
                        signals.s4Unknown,
                        pythonDecision,
                        kotlinDecision,
                        row
                    )

                    if (row.cls == "IN" && row.id == 14) {
                        in14Decisions[presetName] = pythonDecision to kotlinDecision
                    }

                    allRows.add(
                        listOf(
                            presetName,
                            row.cls,
                            row.id.toString(),
                            GateTestAssets.csvEscape(row.question),
                            pythonDecision.toString(),
                            kotlinDecision.toString(),
                            if (pythonDecision == kotlinDecision) "YES" else "NO",
                            format(s1),
                            format(row.s1Top1),
                            format(preset.t1),
                            format(absS1T1),
                            format(signals.s3CovTop3),
                            format(row.s3CovTop3),
                            format(preset.t3),
                            signals.s4Unknown.toString(),
                            row.s4Unknown.toString(),
                            preset.k.toString(),
                            GateTestAssets.csvEscape(reason)
                        ).joinToString(",")
                    )

                    if (pythonDecision != kotlinDecision) {
                        disagreements.add(
                            Disagreement(
                                preset = presetName,
                                cls = row.cls,
                                id = row.id,
                                question = row.question,
                                pythonDecision = pythonDecision,
                                kotlinDecision = kotlinDecision,
                                s1 = s1,
                                t1 = preset.t1,
                                absS1T1 = absS1T1,
                                s3 = signals.s3CovTop3,
                                s3Python = row.s3CovTop3,
                                t3 = preset.t3,
                                s4 = signals.s4Unknown,
                                reason = reason
                            )
                        )
                    }
                }
            }
        }

        // IN 14 must expose s3 = 4/7 and must decide identically in both
        // implementations for both presets.
        val row14 = in14Row ?: error("IN 14 missing from gate_reference.json")
        val expectedFourSevenths = 4.0 / 7.0
        println(
            "K4c IN 14: kotlin s3=${format(in14S3)} python s3=${format(row14.s3CovTop3)} " +
                "4/7=${format(expectedFourSevenths)}"
        )
        assertEquals(
            "IN 14 s3 must be 4/7 in the Kotlin pipeline",
            expectedFourSevenths,
            in14S3,
            1e-9
        )
        assertEquals(
            "IN 14 s3 must be 4/7 in the Python reference",
            expectedFourSevenths,
            row14.s3CovTop3,
            1e-9
        )
        for ((presetName, decisions) in in14Decisions) {
            println(
                "K4c IN 14 $presetName: python=${decisions.first} kotlin=${decisions.second} " +
                    "s3=${format(in14S3)}"
            )
            assertEquals(
                "IN 14 must have the same decision in Python and Kotlin for $presetName",
                decisions.first,
                decisions.second
            )
        }
        assertEquals("IN 14 must be evaluated for both presets", 2, in14Decisions.size)

        embedder.close()
        denseSearch.close()

        val report = File(GateTestAssets.reportDir(), "gate_decisions.csv")
        report.writeText(allRows.joinToString("\n") + "\n", Charsets.UTF_8)
        println("Wrote $report (${reference.size * presets.size} rows)")

        val balancedTotal = reference.size
        val balancedDiffs = disagreements.filter { it.preset == "balanced" }
        val strictDiffs = disagreements.filter { it.preset == "strict" }
        val balancedMatches = balancedTotal - balancedDiffs.size
        val strictMatches = balancedTotal - strictDiffs.size

        println(
            "K4c (b): max |s1_python - s1_kotlin| = ${format(maxS1Delta)} over $s1DeltaRows questions " +
                "(threshold 1e-4); balanced $balancedMatches/$balancedTotal, " +
                "strict $strictMatches/$balancedTotal, disagreements=${disagreements.size}"
        )
        if (disagreements.isEmpty()) {
            println("K4c (b): no disagreements.")
        } else {
            println("K4c (b) disagreement table:")
            println("preset | cls | id | question | python | kotlin | s1 | t1 | abs(s1-t1) | s3 | t3 | reason")
            for (d in disagreements) {
                println(
                    "${d.preset} | ${d.cls} | ${d.id} | ${d.question} | ${d.pythonDecision} | " +
                        "${d.kotlinDecision} | ${format(d.s1)} | ${format(d.t1)} | ${format(d.absS1T1)} | " +
                        "${format(d.s3)} | ${format(d.t3)} | ${d.reason}"
                )
            }
        }

        assertTrue(
            "K4c (b) max |s1_python - s1_kotlin| $maxS1Delta must be <= $s1Epsilon",
            maxS1Delta <= s1Epsilon
        )
        assertTrue(
            "K4c (b) balanced decisions $balancedMatches/$balancedTotal must be >= $minDecisionMatches",
            balancedMatches >= minDecisionMatches
        )
        assertTrue(
            "K4c (b) strict decisions $strictMatches/$balancedTotal must be >= $minDecisionMatches",
            strictMatches >= minDecisionMatches
        )
    }

    private fun buildReason(
        presetName: String,
        preset: GatePreset,
        s1: Double,
        s3: Double,
        s4: Int,
        pythonDecision: Boolean,
        kotlinDecision: Boolean,
        row: GateReferenceRow
    ): String {
        val failing = mutableListOf<String>()
        if (s1 + GateDecision.EPSILON < preset.t1) failing.add("kotlin s1 < t1")
        if (s3 + GateDecision.EPSILON < preset.t3) failing.add("kotlin s3 < t3")
        if (s4 > preset.k) failing.add("kotlin s4 > k")
        if (pythonDecision == kotlinDecision) {
            return if (kotlinDecision) "agree: accepted" else "agree: rejected"
        }
        val direction = if (kotlinDecision) {
            "Kotlin accepted, Python rejected"
        } else {
            "Kotlin rejected, Python accepted"
        }
        val pythonFailing = mutableListOf<String>()
        if (row.s1Top1 + GateDecision.EPSILON < preset.t1) pythonFailing.add("python s1 < t1")
        if (row.s3CovTop3 + GateDecision.EPSILON < preset.t3) pythonFailing.add("python s3 < t3")
        if (row.s4Unknown > preset.k) pythonFailing.add("python s4 > k")
        val kotlinPart = if (failing.isEmpty()) "none" else failing.joinToString("+")
        val pythonPart = if (pythonFailing.isEmpty()) "none" else pythonFailing.joinToString("+")
        return "$direction [$presetName]; Kotlin failing=$kotlinPart; Python failing=$pythonPart; " +
            "python s1=${format(row.s1Top1)} s3=${format(row.s3CovTop3)} s4=${row.s4Unknown}"
    }

    private fun format(value: Double): String = String.format(Locale.ROOT, "%.9f", value)
}
