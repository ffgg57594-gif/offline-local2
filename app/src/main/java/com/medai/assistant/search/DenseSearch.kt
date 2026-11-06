package com.medai.assistant.search

import java.io.Closeable
import java.io.File
import java.io.FileInputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.channels.FileChannel

data class SearchResult(
    val chunkId: Int,
    val page: Int,
    val score: Float
)

/**
 * Dense vector search against precomputed chunk embeddings stored in embeddings.bin.
 * Memory-maps the file (float32 little-endian, 1185x384).
 * Ties are broken by lower chunk id.
 */
class DenseSearch(
    embeddingsFile: File,
    metaRows: Int = 1185,
    metaDim: Int = 384,
    private val chunkPages: IntArray // array of size [rows] mapping index (id-1) -> page
) : Closeable {

    val rows: Int = metaRows
    val dim: Int = metaDim

    private val raf: RandomAccessFile
    private val channel: FileChannel
    private val floatBuffer: FloatBuffer

    init {
        val expectedBytes = metaRows.toLong() * metaDim.toLong() * 4L
        require(embeddingsFile.length() == expectedBytes) {
            "embeddings.bin size mismatch: expected $expectedBytes bytes (${metaRows}x${metaDim}x4), got ${embeddingsFile.length()} bytes"
        }
        require(chunkPages.size >= metaRows) {
            "chunkPages array size (${chunkPages.size}) smaller than metaRows ($metaRows)"
        }

        raf = RandomAccessFile(embeddingsFile, "r")
        channel = raf.channel
        val byteBuffer = channel.map(FileChannel.MapMode.READ_ONLY, 0, channel.size())
        byteBuffer.order(ByteOrder.LITTLE_ENDIAN)
        floatBuffer = byteBuffer.asFloatBuffer()
    }

    /**
     * Search top-k nearest chunks for a given query vector.
     * Ties broken by lower chunk id.
     */
    fun search(queryVector: FloatArray, k: Int = 5): List<SearchResult> {
        require(queryVector.size == dim) {
            "queryVector dimension (${queryVector.size}) does not match index dimension ($dim)"
        }

        val topK = k.coerceAtLeast(1).coerceAtMost(rows)
        // Array of scores
        val scores = FloatArray(rows)

        val localBuf = floatBuffer.duplicate()
        localBuf.rewind()

        val rowFloats = FloatArray(dim)
        for (r in 0 until rows) {
            localBuf.get(rowFloats)
            var dot = 0f
            for (d in 0 until dim) {
                dot += rowFloats[d] * queryVector[d]
            }
            scores[r] = dot
        }

        // Rank by score descending, ties broken by lower chunk id (index + 1)
        val indices = Array(rows) { it }
        indices.sortWith { a, b ->
            val sA = scores[a]
            val sB = scores[b]
            if (sA != sB) {
                sB.compareTo(sA) // Descending score
            } else {
                a.compareTo(b)   // Ascending chunk id (lower id first)
            }
        }

        val results = ArrayList<SearchResult>(topK)
        for (i in 0 until topK) {
            val idx = indices[i]
            val chunkId = idx + 1
            val page = chunkPages[idx]
            results.add(SearchResult(chunkId, page, scores[idx]))
        }
        return results
    }

    override fun close() {
        channel.close()
        raf.close()
    }

    companion object {
        /**
         * Pure in-memory dot-product top-k search on a matrix for unit testing.
         */
        fun searchMatrix(
            matrix: Array<FloatArray>, // [rows][dim]
            chunkPages: IntArray,
            queryVector: FloatArray,
            k: Int = 5
        ): List<SearchResult> {
            val rows = matrix.size
            if (rows == 0) return emptyList()
            val dim = matrix[0].size
            require(queryVector.size == dim) { "Dimension mismatch" }

            val topK = k.coerceAtLeast(1).coerceAtMost(rows)
            val scores = FloatArray(rows)
            for (r in 0 until rows) {
                var dot = 0f
                val row = matrix[r]
                for (d in 0 until dim) {
                    dot += row[d] * queryVector[d]
                }
                scores[r] = dot
            }

            val indices = Array(rows) { it }
            indices.sortWith { a, b ->
                val sA = scores[a]
                val sB = scores[b]
                if (sA != sB) {
                    sB.compareTo(sA)
                } else {
                    a.compareTo(b) // tie break lower id
                }
            }

            val results = ArrayList<SearchResult>(topK)
            for (i in 0 until topK) {
                val idx = indices[i]
                results.add(SearchResult(idx + 1, chunkPages[idx], scores[idx]))
            }
            return results
        }
    }
}
