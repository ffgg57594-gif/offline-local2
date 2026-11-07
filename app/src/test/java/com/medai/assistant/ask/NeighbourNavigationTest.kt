package com.medai.assistant.ask

import com.medai.assistant.data.JdbcChunkRepository
import com.medai.assistant.gate.GateTestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class NeighbourNavigationTest {

    private val repository by lazy { JdbcChunkRepository(GateTestAssets.database) }

    @Test
    fun firstChunkHasNoPreviousChunk() {
        val first = repository.getById(1)
        assertNotNull(first)
        assertNull(repository.getNeighbour(1, -1))
    }

    @Test
    fun lastChunkHasNoNextChunk() {
        val last = repository.getById(1185)
        assertNotNull(last)
        assertNull(repository.getNeighbour(1185, 1))
    }

    @Test
    fun deltaZeroReturnsTheSameChunk() {
        val chunk = repository.getById(42)
        assertNotNull(chunk)
        assertEquals(chunk, repository.getNeighbour(42, 0))
    }

    @Test
    fun neighboursStayInsideTheSameBook() {
        val sampleIds = listOf(1, 2, 50, 90, 300, 700, 1000, 1184, 1185)
        for (id in sampleIds) {
            val chunk = repository.getById(id) ?: continue
            val previous = repository.getNeighbour(id, -1)
            val next = repository.getNeighbour(id, 1)
            if (previous != null) {
                assertEquals(
                    "previous neighbour of chunk $id left its book",
                    chunk.bookName,
                    previous.bookName
                )
            }
            if (next != null) {
                assertEquals(
                    "next neighbour of chunk $id left its book",
                    chunk.bookName,
                    next.bookName
                )
            }
        }
    }

    @Test
    fun navigationWalksForwardAndBackward() {
        val start = repository.getById(2)
        assertNotNull(start)
        val forward = repository.getNeighbour(2, 1)
        assertNotNull(forward)
        val backward = repository.getNeighbour(forward!!.id, -1)
        assertEquals(2, backward?.id)
    }
}
