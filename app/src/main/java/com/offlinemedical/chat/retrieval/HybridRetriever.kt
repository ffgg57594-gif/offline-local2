package com.offlinemedical.chat.retrieval

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class Chunk(val id: Long, val bookName: String, val pageNumber: Int, val text: String, val section: String?)
data class RetrievalResult(val chunks: List<Chunk>, val scores: List<Float>, val fusedScore: Float)

class HybridRetriever(private val dbPath: String, private val embeddingsPath: String) {
    suspend fun search(query: String, topK: Int = 5): RetrievalResult = withContext(Dispatchers.Default) {
        // Stub: real implementation loads memory-mapped embeddings, runs brute-force dense search,
        // FTS5 BM25, RRF fusion, glossary boost, neighbor merge.
        RetrievalResult(emptyList(), emptyList(), 0f)
    }
}
