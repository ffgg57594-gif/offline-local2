package com.medai.assistant.data

interface ChunkRepository {
    fun count(): Int
    fun getById(id: Int): Chunk?
    fun getByIds(ids: List<Int>): List<Chunk>
    fun getAllPages(expectedCount: Int = 1185): IntArray

    /**
     * Previous/next chunk in the same book. Returns null at the first/last
     * chunk of a book. [delta] is -1 for previous and +1 for next.
     */
    fun getNeighbour(chunkId: Int, delta: Int): Chunk?
}

data class Chunk(
    val id: Int,
    val bookName: String,
    val page: Int,
    val section: String,
    val text: String
)
