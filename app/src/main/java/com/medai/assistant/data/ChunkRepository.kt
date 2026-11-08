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

    /** 1-based position of [chunkId] inside its book, and the book chunk count. */
    fun getPositionInBook(chunkId: Int): Pair<Int, Int>?

    /** First embedded book, used by the empty state line. */
    fun primaryBook(): BookInfo?
}

data class Chunk(
    val id: Int,
    val bookName: String,
    val page: Int,
    val section: String,
    val text: String,
    /** Display-only text with PDF bullet/private-use glyphs cleaned. */
    val displayText: String = text
)

data class BookInfo(
    val rawName: String,
    val pages: Int,
    val chunks: Int
)
