package com.medai.assistant.search

import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.tokenizer.Tokenizer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs

class DenseSearchTest {

    @Test
    fun testDenseSearchOnSmallFakeMatrix() {
        val matrix = arrayOf(
            floatArrayOf(1.0f, 0.0f, 0.0f), // row 0 (chunkId = 1): score = 1.0 * 1.0 = 1.0
            floatArrayOf(0.0f, 1.0f, 0.0f), // row 1 (chunkId = 2): score = 1.0 * 0.0 = 0.0
            floatArrayOf(0.8f, 0.6f, 0.0f), // row 2 (chunkId = 3): score = 0.8
            floatArrayOf(1.0f, 0.0f, 0.0f)  // row 3 (chunkId = 4): score = 1.0 (tie with chunkId 1)
        )
        val chunkPages = intArrayOf(10, 20, 30, 40)

        val queryVector = floatArrayOf(1.0f, 0.0f, 0.0f)

        // Test k = 3
        val results = DenseSearch.searchMatrix(matrix, chunkPages, queryVector, k = 3)
        assertEquals(3, results.size)

        // Expected order:
        // Chunk 1 and Chunk 4 both have dot product 1.0f.
        // Tie must be broken by lower chunk id: chunk 1 first, then chunk 4!
        assertEquals(1, results[0].chunkId)
        assertEquals(10, results[0].page)
        assertEquals(1.0f, results[0].score, 1e-5f)

        assertEquals(4, results[1].chunkId)
        assertEquals(40, results[1].page)
        assertEquals(1.0f, results[1].score, 1e-5f)

        // Chunk 3 has score 0.8f
        assertEquals(3, results[2].chunkId)
        assertEquals(30, results[2].page)
        assertEquals(0.8f, results[2].score, 1e-5f)

        // Test k > rows: should clamp to available rows without crashing
        val resultsAll = DenseSearch.searchMatrix(matrix, chunkPages, queryVector, k = 10)
        assertEquals(4, resultsAll.size)
        assertEquals(2, resultsAll[3].chunkId)
    }

    @Test
    fun testRetrievalParityAgainstPythonGolden120() {
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

        val embeddingsBinFile = sequenceOf(
            File("src/main/assets/embeddings.bin"),
            File("app/src/main/assets/embeddings.bin"),
            File("../app/src/main/assets/embeddings.bin"),
            File("assets/embeddings.bin")
        ).firstOrNull { it.exists() }

        val dbFile = sequenceOf(
            File("src/main/assets/books_knowledge.db"),
            File("app/src/main/assets/books_knowledge.db"),
            File("../app/src/main/assets/books_knowledge.db"),
            File("assets/books_knowledge.db")
        ).firstOrNull { it.exists() }

        val csvStream = DenseSearchTest::class.java.classLoader?.getResourceAsStream("retrieval_top5.csv")
            ?: File("src/test/resources/retrieval_top5.csv").takeIf { it.exists() }?.inputStream()
            ?: File("app/src/test/resources/retrieval_top5.csv").takeIf { it.exists() }?.inputStream()
            ?: File("eval/retrieval_top5.csv").takeIf { it.exists() }?.inputStream()
            ?: File("../eval/retrieval_top5.csv").takeIf { it.exists() }?.inputStream()

        if (modelFile == null || tokenizerBinFile == null || embeddingsBinFile == null || dbFile == null || csvStream == null) {
            println("Skipping testRetrievalParityAgainstPythonGolden120: missing assets")
            return
        }

        // Load chunk pages from database
        val chunkPages = IntArray(1185)
        java.sql.DriverManager.getConnection("jdbc:sqlite:${dbFile.absolutePath}").use { conn ->
            conn.createStatement().use { stmt ->
                val rs = stmt.executeQuery("SELECT id, page FROM chunks ORDER BY id")
                while (rs.next()) {
                    val id = rs.getInt("id")
                    val page = rs.getInt("page")
                    if (id in 1..1185) {
                        chunkPages[id - 1] = page
                    }
                }
            }
        }

        // Measure Tokenizer Load Time
        val tokStart = System.nanoTime()
        val tokenizer = Tokenizer.fromBinaryFile(tokenizerBinFile)
        val tokenizerLoadMs = (System.nanoTime() - tokStart) / 1_000_000.0

        // Measure Embedder Load Time
        val embStart = System.nanoTime()
        val embedder = OnnxEmbedder(modelFile, tokenizer)
        val embedderLoadMs = (System.nanoTime() - embStart) / 1_000_000.0

        val denseSearch = DenseSearch(embeddingsBinFile, metaRows = 1185, metaDim = 384, chunkPages = chunkPages)

        // Parse retrieval_top5.csv
        val lines = csvStream.bufferedReader(Charsets.UTF_8).readLines()
        if (lines.isEmpty()) return
        val header = parseCsvLine(lines[0])
        val qRows = mutableListOf<Map<String, String>>()
        for (i in 1 until lines.size) {
            val line = lines[i].trim()
            if (line.isEmpty()) continue
            val cols = parseCsvLine(line)
            val map = mutableMapOf<String, String>()
            for (c in header.indices) {
                if (c < cols.size) {
                    map[header[c]] = cols[c]
                }
            }
            qRows.add(map)
        }

        println("Loaded ${qRows.size} golden questions from retrieval_top5.csv for parity check.")

        // Prepare report file: build/reports/parity/retrieval_parity.csv
        val reportDir = File("build/reports/parity").takeIf { it.isAbsolute }
            ?: (if (File("app").exists()) File("build/reports/parity") else File("../build/reports/parity"))
        reportDir.mkdirs()
        val retrievalReportFile = File(reportDir, "retrieval_parity.csv")
        val timingReportFile = File(reportDir, "timing_jvm.csv")

        val retrievalCsvLines = mutableListOf<String>()
        retrievalCsvLines.add("cls,id,question,python_top1_chunk,kotlin_top1_chunk,python_s1,kotlin_s1,abs_delta,python_top3,kotlin_top3")

        var top1Matches = 0
        var top3OverlapSum = 0.0
        var deltaS1WithinThreshold = 0
        val deltas = mutableListOf<Double>()
        val embedLatenciesMs = mutableListOf<Double>()

        for (row in qRows) {
            val cls = row["cls"] ?: ""
            val qid = row["id"]?.toIntOrNull() ?: 0
            val question = row["question"] ?: ""
            val expectedRank1Chunk = row["rank_1_chunk_id"]?.toIntOrNull() ?: 0
            val expectedRank1Score = row["rank_1_dense_cosine"]?.toDoubleOrNull() ?: 0.0

            val pyChunk1 = row["rank_1_chunk_id"] ?: ""
            val pyChunk2 = row["rank_2_chunk_id"] ?: ""
            val pyChunk3 = row["rank_3_chunk_id"] ?: ""
            val pythonTop3Str = "\"[$pyChunk1, $pyChunk2, $pyChunk3]\""

            val expectedTop3Chunks = setOfNotNull(
                pyChunk1.toIntOrNull(),
                pyChunk2.toIntOrNull(),
                pyChunk3.toIntOrNull()
            )

            val t0 = System.nanoTime()
            val queryVec = embedder.embedQuery(question)
            val embedDurationMs = (System.nanoTime() - t0) / 1_000_000.0
            embedLatenciesMs.add(embedDurationMs)

            val results = denseSearch.search(queryVec, k = 5)

            val actualRank1Chunk = results[0].chunkId
            val actualRank1Score = results[0].score.toDouble()
            val actualTop3List = results.take(3).map { it.chunkId }
            val actualTop3Chunks = actualTop3List.toSet()
            val kotlinTop3Str = "\"${actualTop3List}\""

            if (actualRank1Chunk == expectedRank1Chunk) {
                top1Matches++
            }

            val overlap = actualTop3Chunks.intersect(expectedTop3Chunks).size.toDouble() / 3.0
            top3OverlapSum += overlap

            val delta = abs(actualRank1Score - expectedRank1Score)
            deltas.add(delta)
            if (delta <= 0.01) {
                deltaS1WithinThreshold++
            }

            val safeQuestion = "\"" + question.replace("\"", "\"\"") + "\""
            retrievalCsvLines.add(
                "$cls,$qid,$safeQuestion,$expectedRank1Chunk,$actualRank1Chunk,${String.format("%.6f", expectedRank1Score)},${String.format("%.6f", actualRank1Score)},${String.format("%.6f", delta)},$pythonTop3Str,$kotlinTop3Str"
            )
        }

        retrievalReportFile.writeText(retrievalCsvLines.joinToString("\n") + "\n", Charsets.UTF_8)
        println("Wrote retrieval parity report to ${retrievalReportFile.absolutePath} (${qRows.size} rows)")

        val rootRetrievalReport = File("build/reports/parity/retrieval_parity.csv")
        if (rootRetrievalReport.canonicalPath != retrievalReportFile.canonicalPath) {
            rootRetrievalReport.parentFile?.mkdirs()
            rootRetrievalReport.writeText(retrievalCsvLines.joinToString("\n") + "\n", Charsets.UTF_8)
        }

        // Compute timing percentiles
        embedLatenciesMs.sort()
        val n = embedLatenciesMs.size
        val p50 = if (n > 0) embedLatenciesMs[(n * 0.50).toInt().coerceAtMost(n - 1)] else 0.0
        val p95 = if (n > 0) embedLatenciesMs[(n * 0.95).toInt().coerceAtMost(n - 1)] else 0.0
        val maxTiming = if (n > 0) embedLatenciesMs.last() else 0.0

        val timingCsvLines = listOf(
            "metric,value_ms",
            "tokenizer_load_ms,${String.format("%.2f", tokenizerLoadMs)}",
            "embedder_load_ms,${String.format("%.2f", embedderLoadMs)}",
            "embed_120_queries_p50_ms,${String.format("%.2f", p50)}",
            "embed_120_queries_p95_ms,${String.format("%.2f", p95)}",
            "embed_120_queries_max_ms,${String.format("%.2f", maxTiming)}"
        )
        timingReportFile.writeText(timingCsvLines.joinToString("\n") + "\n", Charsets.UTF_8)
        println("Wrote timing report to ${timingReportFile.absolutePath}")

        val rootTimingReport = File("build/reports/parity/timing_jvm.csv")
        if (rootTimingReport.canonicalPath != timingReportFile.canonicalPath) {
            rootTimingReport.parentFile?.mkdirs()
            rootTimingReport.writeText(timingCsvLines.joinToString("\n") + "\n", Charsets.UTF_8)
        }

        deltas.sort()
        val total = qRows.size
        val top1Rate = (top1Matches.toDouble() / total) * 100.0
        val top3OverlapRate = (top3OverlapSum / total) * 100.0
        val deltaRate = (deltaS1WithinThreshold.toDouble() / total) * 100.0

        embedder.close()
        denseSearch.close()

        assertTrue("Top-1 match rate (${top1Rate}%) must be >= 90.0%", top1Rate >= 90.0)
        assertTrue("Top-3 set overlap (${top3OverlapRate}%) must be >= 80.0%", top3OverlapRate >= 80.0)
        assertTrue("|delta s1| <= 0.01 rate (${deltaRate}%) must be >= 95.0%", deltaRate >= 95.0)
    }

    private fun parseCsvLine(line: String): List<String> {
        val result = mutableListOf<String>()
        val sb = StringBuilder()
        var inQuotes = false
        var i = 0
        while (i < line.length) {
            val c = line[i]
            if (c == '"') {
                if (inQuotes && i + 1 < line.length && line[i + 1] == '"') {
                    sb.append('"')
                    i++
                } else {
                    inQuotes = !inQuotes
                }
            } else if (c == ',' && !inQuotes) {
                result.add(sb.toString().trim())
                sb.clear()
            } else {
                sb.append(c)
            }
            i++
        }
        result.add(sb.toString().trim())
        return result
    }
}
