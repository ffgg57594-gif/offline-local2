package com.medai.assistant.data

interface ChunkRepository {
    fun count(): Int
    fun getById(id: Int): Chunk?
    fun getByIds(ids: List<Int>): List<Chunk>
    fun getAllPages(expectedCount: Int = 1185): IntArray
}

data class Chunk(
    val id: Int,
    val bookName: String,
    val page: Int,
    val section: String,
    val text: String
)
