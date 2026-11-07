package com.medai.assistant.ask

import com.medai.assistant.data.JdbcChunkRepository
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.gate.GateConfig
import com.medai.assistant.gate.GateReference
import com.medai.assistant.gate.GateTestAssets
import com.medai.assistant.gate.GateVocab
import com.medai.assistant.gate.JdbcGateDatabase
import com.medai.assistant.gate.Json
import com.medai.assistant.gate.asInt
import com.medai.assistant.gate.asObject
import com.medai.assistant.gate.asString
import com.medai.assistant.search.DenseSearch
import com.medai.assistant.tokenizer.Tokenizer
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * K5a end-to-end JVM test with the real ONNX model.
 *
 * Runs the exact [DeviceAskEngine] used by the app for golden questions 1..10
 * under both presets, then compares:
 *  - the accept/reject decision with CI-generated `assets/gate_reference.json`;
 *  - the top-3 chunk ids with the Python `eval/retrieval_top5.csv` reference.
 *
 * The report is written to `build/reports/k5a/e2e_10.csv` so CI can publish it.
 */
class PipelineEndToEndTest {

    private val goldenFile: File
        get() = GateTestAssets.require(
            listOf(
                "../eval/golden_v3.draft.jsonl",
                "eval/golden_v3.draft.jsonl",
                "../../eval/golden_v3.draft.jsonl"
            ),
            "golden_v3.draft.jsonl"
        )

    @Test
    fun pipelineMatchesGoldenAndPythonReferenceForTenQuestions() {
        val golden = loadGolden(goldenFile)
        // Both reference files contain 60 in-scope and 60 out-of-scope rows, and
        // each group numbers its questions from 1. Golden ids 1..10 are the
        // in-scope questions, so filter the group before keying by id.
        val references = GateReference.load(GateTestAssets.reference)
            .filter { it.group == "in" }
            .associateBy { it.id }
        val retrieval = GateTestAssets.parseCsv(GateTestAssets.retrievalCsv)
            .filter { it["group"] == "in" }
            .associateBy { it.getValue("id").toInt() }

        val repository = JdbcChunkRepository(GateTestAssets.database)
        val tokenizer = Tokenizer.fromBinaryFile(GateTestAssets.tokenizerBin)
        val embedder = OnnxEmbedder(GateTestAssets.model, tokenizer)
        val pages = repository.getAllPages(1185)
        val denseSearch = DenseSearch(GateTestAssets.embeddings, 1185, 384, pages)
        val vocab = GateVocab.load(GateTestAssets.vocab)
        val config = GateConfig.load(GateTestAssets.config)

        val rows = mutableListOf<String>()
        val failures = mutableListOf<String>()

        try {
            JdbcGateDatabase(GateTestAssets.database).use { database ->
                val engine = DeviceAskEngine(
                    repository = repository,
                    tokenizer = tokenizer,
                    embedder = embedder,
                    denseSearch = denseSearch,
                    gateVocab = vocab,
                    gateConfig = config,
                    gateDatabase = database
                )

                rows.add(
                    "id,question,preset,expected_decision,actual_decision,decision_match," +
                        "expected_top3,actual_top3,top3_match,pages,total_ms"
                )

                for (id in 1..10) {
                    val goldenRow = golden[id]
                        ?: error("golden question id $id is missing")
                    val reference = references[id]
                        ?: error("gate_reference row id $id is missing")
                    val retrievalRow = retrieval[id]
                        ?: error("retrieval_top5 row id $id is missing")
                    val expectedTop3 = listOf(
                        retrievalRow.getValue("rank_1_chunk_id"),
                        retrievalRow.getValue("rank_2_chunk_id"),
                        retrievalRow.getValue("rank_3_chunk_id")
                    ).map { it.toInt() }

                    for (preset in listOf("balanced", "strict")) {
                        val answer = runBlocking { engine.answer(goldenRow, preset) }
                        val expectedDecision = when (preset) {
                            "balanced" -> reference.balancedDecision
                            else -> reference.strictDecision
                        }
                        val actualDecision = answer.decision.accepted
                        val actualTop3 = answer.top3.map { it.chunkId }
                        val decisionMatch = actualDecision == expectedDecision
                        val top3Match = actualTop3 == expectedTop3

                        if (!answer.decision.gateAvailable) {
                            failures.add(
                                "id=$id preset=$preset gate unavailable: " +
                                    (answer.decision.gateError ?: "unknown")
                            )
                        }
                        if (actualTop3.size != 3) {
                            failures.add(
                                "id=$id preset=$preset returned ${actualTop3.size} passages"
                            )
                        }
                        if (!decisionMatch) {
                            failures.add(
                                "id=$id preset=$preset decision expected=$expectedDecision " +
                                    "actual=$actualDecision " +
                                    "(s1=${answer.decision.s1}, s3=${answer.decision.s3}, " +
                                    "s4=${answer.decision.s4})"
                            )
                        }
                        if (!top3Match) {
                            failures.add(
                                "id=$id preset=$preset top3 expected=$expectedTop3 " +
                                    "actual=$actualTop3"
                            )
                        }

                        val pageList = answer.top3.joinToString("|") { it.page.toString() }
                        rows.add(
                            listOf(
                                id.toString(),
                                GateTestAssets.csvEscape(goldenRow),
                                preset,
                                expectedDecision.toString(),
                                actualDecision.toString(),
                                if (decisionMatch) "YES" else "NO",
                                expectedTop3.joinToString("|"),
                                actualTop3.joinToString("|"),
                                if (top3Match) "YES" else "NO",
                                pageList,
                                answer.timings.totalMs.toString()
                            ).joinToString(",")
                        )
                    }
                }
            }
        } finally {
            embedder.close()
            denseSearch.close()
        }

        val reportDir = if (File("app").exists()) {
            File("build/reports/k5a")
        } else {
            File("../build/reports/k5a")
        }
        reportDir.mkdirs()
        File(reportDir, "e2e_10.csv").writeText(rows.joinToString("\n") + "\n", Charsets.UTF_8)

        assertTrue(
            "K5a end-to-end mismatches:\n" + failures.joinToString("\n"),
            failures.isEmpty()
        )
    }

    private fun loadGolden(file: File): Map<Int, String> {
        val questions = LinkedHashMap<Int, String>()
        file.readLines(Charsets.UTF_8).forEach { line ->
            if (line.isBlank()) return@forEach
            val obj = Json.parse(line).asObject()
            val id = obj["id"]?.asInt() ?: return@forEach
            if (id in 1..10) {
                questions[id] = obj["q"]?.asString() ?: error("golden id $id has no question")
            }
        }
        return questions
    }
}
