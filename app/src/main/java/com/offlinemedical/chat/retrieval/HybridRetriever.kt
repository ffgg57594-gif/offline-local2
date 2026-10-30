package com.offlinemedical.chat.retrieval

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.sqrt

data class Chunk(val id: Long, val bookName: String, val pageNumber: Int, val text: String, val section: String?)
data class RetrievalResult(val chunks: List<Chunk>, val scores: List<Float>, val fusedScore: Float)

class HybridRetriever(private val dbPath: String, private val embeddingsPath: String) {
    private val cache = LinkedHashMap<String, RetrievalResult>(64, 0.75f, true)

    suspend fun search(query: String, topK: Int = 5): RetrievalResult = withContext(Dispatchers.Default) {
        cache[query]?.let { return@withContext it }
        // Dense brute-force + FTS5 BM25 + RRF fusion (scaffold)
        val result = RetrievalResult(emptyList(), emptyList(), 0f)
        if (cache.size >= 64) cache.remove(cache.keys.first())
        cache[query] = result
        result
    }

    companion object {
        fun cosine(a: FloatArray, b: FloatArray): Float {
            var dot = 0f; var na = 0f; var nb = 0f
            for (i in a.indices) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i] }
            return if (na == 0f || nb == 0f) 0f else dot / (sqrt(na)*sqrt(nb))
        }
        fun rrf(ranks: List<List<Int>>, k: Int = 60): Map<Int, Float> {
            val scores = mutableMapOf<Int, Float>()
            for (list in ranks) for ((i, id) in list.withIndex()) {
                scores[id] = (scores[id] ?: 0f) + 1f / (k + i + 1)
            }
            return scores
        }
    }
}
