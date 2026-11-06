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
        // 4 items, dimension 3
        // row 0: [1.0, 0.0, 0.0] -> chunk 1, page 10
        // row 1: [0.0, 1.0, 0.0] -> chunk 2, page 20
        // row 2: [0.0, 1.0, 0.0] -> chunk 3, page 30 (tie with chunk 2 on dot product with [0, 1, 0])
        // row 3: [0.0, 0.0, 1.0] -> chunk 4, page 40
        val matrix = arrayOf(
            floatArrayOf(1.0f, 0.0f, 0.0f),
            floatArrayOf(0.0f, 1.0f, 0.0f),
            floatArrayOf(0.0f, 1.0f, 0.0f),
            floatArrayOf(0.0f, 0.0f, 1.0f)
        )
        val pages = intArrayOf(10, 20, 30, 40)

        // Query: [0.0, 1.0, 0.0]
        // Expected dot products:
        // row 0: 0.0
        // row 1: 1.0 (chunk 2)
        // row 2: 1.0 (chunk 3)
        // row 3: 0.0 (chunk 4)
        // Order: chunk 2 (1.0), chunk 3 (1.0 - tie broken by lower id 2 < 3), then chunk 1 (0.0), chunk 4 (0.0)

        // Test with k=2
        val top2 = DenseSearch.searchMatrix(matrix, pages, floatArrayOf(0f, 1f, 0f), k = 2)
        assertEquals(2, top2.size)
        assertEquals(2, top2[0].chunkId)
        assertEquals(20, top2[0].page)
        assertEquals(1.0f, top2[0].score, 1e-5f)

        assertEquals(3, top2[1].chunkId)
        assertEquals(30, top2[1].page)
        assertEquals(1.0f, top2[1].score, 1e-5f)

        // Test with k larger than rows (k=10 on 4 rows)
        val topAll = DenseSearch.searchMatrix(matrix, pages, floatArrayOf(0f, 1f, 0f), k = 10)
        assertEquals(4, topAll.size)
        assertEquals(2, topAll[0].chunkId)
        assertEquals(3, topAll[1].chunkId)
        assertEquals(1, topAll[2].chunkId) // tie 0.0 between id 1 and id 4: id 1 first
        assertEquals(4, topAll[3].chunkId)
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

        val tokenizer = Tokenizer.fromBinaryFile(tokenizerBinFile)
        val embedder = OnnxEmbedder(modelFile, tokenizer)
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

        var top1Matches = 0
        var top3OverlapSum = 0.0
        var deltaS1WithinThreshold = 0
        val deltas = mutableListOf<Double>()
        val top1Mismatches = mutableListOf<String>()

        for (row in qRows) {
            val qid = row["id"]?.toIntOrNull() ?: 0
            val question = row["question"] ?: ""
            val expectedRank1Chunk = row["rank_1_chunk_id"]?.toIntOrNull() ?: 0
            val expectedRank1Score = row["rank_1_dense_cosine"]?.toDoubleOrNull() ?: 0.0

            val expectedTop3Chunks = setOfNotNull(
                row["rank_1_chunk_id"]?.toIntOrNull(),
                row["rank_2_chunk_id"]?.toIntOrNull(),
                row["rank_3_chunk_id"]?.toIntOrNull()
            )

            val queryVec = embedder.embedQuery(question)
            val results = denseSearch.search(queryVec, k = 5)

            val actualRank1Chunk = results[0].chunkId
            val actualRank1Score = results[0].score.toDouble()
            val actualTop3Chunks = results.take(3).map { it.chunkId }.toSet()

            // Top-1 chunk id match
            if (actualRank1Chunk == expectedRank1Chunk) {
                top1Matches++
            } else {
                top1Mismatches.add(
                    "Q#$qid: expected chunk $expectedRank1Chunk (s=$expectedRank1Score), got $actualRank1Chunk (s=$actualRank1Score) - '$question'"
                )
            }

            // Top-3 set overlap
            val overlap = actualTop3Chunks.intersect(expectedTop3Chunks).size.toDouble() / 3.0
            top3OverlapSum += overlap

            // Delta s1
            val delta = abs(actualRank1Score - expectedRank1Score)
            deltas.add(delta)
            if (delta <= 0.01) {
                deltaS1WithinThreshold++
            }
        }

        deltas.sort()
        val total = qRows.size
        val top1Rate = (top1Matches.toDouble() / total) * 100.0
        val top3OverlapRate = (top3OverlapSum / total) * 100.0
        val deltaRate = (deltaS1WithinThreshold.toDouble() / total) * 100.0

        val maxDelta = if (deltas.isNotEmpty()) deltas.last() else 0.0
        val meanDelta = if (deltas.isNotEmpty()) deltas.average() else 0.0
        val p95Idx = ((total * 0.95).toInt()).coerceAtMost(deltas.size - 1)
        val p95Delta = if (deltas.isNotEmpty()) deltas[p95Idx] else 0.0

        println("\n=========================================================================")
        println("RETRIEVAL PARITY SUMMARY (Against Python eval/retrieval_top5.csv)")
        println("=========================================================================")
        println(String.format("Top-1 Chunk ID match  : %d / %d (%.2f%%) [Requirement >= 90.0%%]", top1Matches, total, top1Rate))
        println(String.format("Top-3 Set Overlap     : %.2f%% [Requirement >= 80.0%%]", top3OverlapRate))
        println(String.format("|delta s1| <= 0.01    : %d / %d (%.2f%%) [Requirement >= 95.0%%]", deltaS1WithinThreshold, total, deltaRate))
        println("-------------------------------------------------------------------------")
        println("|delta s1| Distribution : Max = ${String.format("%.6f", maxDelta)}, p95 = ${String.format("%.6f", p95Delta)}, Mean = ${String.format("%.6f", meanDelta)}")
        println("-------------------------------------------------------------------------")
        if (top1Mismatches.isEmpty()) {
            println("Top-1 mismatches: NONE (100% Top-1 match!)")
        } else {
            println("Top-1 mismatches (${top1Mismatches.size}):")
            for (m in top1Mismatches) {
                println("  * $m")
            }
        }
        println("=========================================================================\n")

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
