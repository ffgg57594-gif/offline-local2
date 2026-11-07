package com.medai.assistant.gate

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.Locale

/**
 * K4 test (a): for all 120 golden questions, feed the Python top-3 chunk ids
 * from `retrieval_top5.csv` into the Kotlin content-stem/s3/s4 code and require
 * an exact match with `gate_reference.json`.
 *
 * The Python source definitions are printed and written to
 * `build/reports/parity/gate_python_definitions.txt` so the port can be audited.
 */
class GateStemsParityTest {

    @Test
    fun testS3AndS4MatchPythonReferenceUsingPythonTop3() {
        val vocab = GateVocab.load(GateTestAssets.vocab)
        val reference = GateReference.load(GateTestAssets.reference)
        val csvRows = GateTestAssets.parseCsv(GateTestAssets.retrievalCsv)
        // In-scope and out-of-scope id ranges both start at 1, so key by
        // (group, id) exactly as gate_reference.json does.
        val csvByGroupId = csvRows.associateBy {
            "${it["group"]}|${it["id"]?.toIntOrNull() ?: -1}"
        }

        dumpPythonDefinitions()

        val outRows = mutableListOf<String>()
        outRows.add("cls,id,question,kotlin_s3,python_s3,s3_match,kotlin_s4,python_s4,s4_match,stems,top3_chunk_ids")
        val differences = mutableListOf<String>()

        JdbcGateDatabase(GateTestAssets.database).use { database ->
            for (row in reference) {
                val csv = csvByGroupId["${row.group}|${row.id}"]
                    ?: error("retrieval_top5.csv has no row for group=${row.group} id=${row.id}")
                val top3 = listOf("rank_1_chunk_id", "rank_2_chunk_id", "rank_3_chunk_id")
                    .map { key -> csv[key]?.toIntOrNull() ?: error("missing $key for id=${row.id}") }
                val signals = GateSignals.compute(row.question, top3, database, vocab)

                val kotlinS3 = String.format(Locale.ROOT, "%.6f", signals.s3CovTop3)
                val pythonS3 = String.format(Locale.ROOT, "%.6f", row.s3CovTop3)
                val s3Match = kotlinS3 == pythonS3
                val s4Match = signals.s4Unknown == row.s4Unknown
                val stemsCell = signals.stems.joinToString(" ")
                val top3Cell = top3.joinToString(",")

                outRows.add(
                    listOf(
                        row.cls,
                        row.id.toString(),
                        GateTestAssets.csvEscape(row.question),
                        kotlinS3,
                        pythonS3,
                        if (s3Match) "YES" else "NO",
                        signals.s4Unknown.toString(),
                        row.s4Unknown.toString(),
                        if (s4Match) "YES" else "NO",
                        GateTestAssets.csvEscape(stemsCell),
                        GateTestAssets.csvEscape(top3Cell)
                    ).joinToString(",")
                )

                if (!s3Match || !s4Match) {
                    differences.add(
                        "id=${row.id} cls=${row.cls} kotlin_s3=$kotlinS3 python_s3=$pythonS3 " +
                            "kotlin_s4=${signals.s4Unknown} python_s4=${row.s4Unknown} " +
                            "stems=[$stemsCell] top3=[$top3Cell] | ${row.question}"
                    )
                }
            }
        }

        val report = File(GateTestAssets.reportDir(), "gate_stems_parity.csv")
        report.writeText(outRows.joinToString("\n") + "\n", Charsets.UTF_8)
        println("Wrote $report (${reference.size} rows)")

        if (differences.isEmpty()) {
            println("K4 (a): no s3/s4 differences in ${reference.size}/${reference.size} questions.")
        } else {
            println("K4 (a): ${differences.size} difference(s):")
            differences.forEach { println("  $it") }
        }
        assertTrue(
            "K4 (a) s3/s4 must match gate_reference.json exactly; differences=${differences.size}: " +
                differences.joinToString(" || "),
            differences.isEmpty()
        )
    }

    private fun dumpPythonDefinitions() {
        val signalsFile = GateTestAssets.find(
            listOf("scripts/gate_signals.py", "../scripts/gate_signals.py")
        ) ?: error("scripts/gate_signals.py not found")
        val ruleFile = GateTestAssets.find(
            listOf("scripts/gate_rule.py", "../scripts/gate_rule.py")
        ) ?: error("scripts/gate_rule.py not found")

        val signalsSource = signalsFile.readText(Charsets.UTF_8)
        val ruleSource = ruleFile.readText(Charsets.UTF_8)
        val text = buildString {
            appendLine("# Python refusal-gate definitions copied by the K4 parity test")
            appendLine("# Source: scripts/gate_signals.py")
            appendLine()
            appendLine(functionBlock(signalsSource, "content_stems"))
            appendLine()
            appendLine(functionBlock(signalsSource, "stem_doc_freq"))
            appendLine()
            appendLine(functionBlock(signalsSource, "chunk_contains_stem"))
            appendLine()
            appendLine(functionBlock(signalsSource, "compute_signals"))
            appendLine()
            appendLine("# Source: scripts/gate_rule.py")
            appendLine()
            appendLine(functionBlock(ruleSource, "accept"))
        }
        val out = File(GateTestAssets.reportDir(), "gate_python_definitions.txt")
        out.writeText(text, Charsets.UTF_8)
        println("=== Python definitions copied for K4 ===")
        println(text)
        println("=== End Python definitions ===")
        println("Wrote $out")
    }

    private fun functionBlock(source: String, name: String): String {
        val start = source.indexOf("def $name(")
        if (start < 0) return "def $name(...): # not found"
        val nextDef = source.indexOf("\ndef ", start + 1)
        val nextSection = source.indexOf(
            "\n# ---------------------------------------------------------------------------",
            start + 1
        )
        val candidates = listOf(nextDef, nextSection).filter { it > start }
        val end = candidates.minOrNull() ?: source.length
        return source.substring(start, end).trimEnd()
    }
}
