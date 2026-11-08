package com.medai.assistant.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import java.io.File
import java.security.MessageDigest

class ChunkRepositoryTest {

    companion object {
        private lateinit var dbFile: File
        private lateinit var metaFile: File
        private lateinit var repository: JdbcChunkRepository

        @BeforeClass
        @JvmStatic
        fun setUp() {
            // Find books_knowledge.db in app/src/main/assets
            val candidates = listOf(
                File("src/main/assets/books_knowledge.db"),
                File("app/src/main/assets/books_knowledge.db"),
                File("../app/src/main/assets/books_knowledge.db")
            )
            val found = candidates.firstOrNull { it.exists() }
            assertNotNull("books_knowledge.db must exist for tests", found)
            dbFile = found!!

            val metaCandidates = listOf(
                File("src/main/assets/embeddings_meta.json"),
                File("app/src/main/assets/embeddings_meta.json"),
                File("../app/src/main/assets/embeddings_meta.json")
            )
            metaFile = metaCandidates.firstOrNull { it.exists() }!!
            repository = JdbcChunkRepository(dbFile)
        }
    }

    @Test
    fun testCountIs1185() {
        assertEquals(1185, repository.count())
    }

    @Test
    fun testIdsAre1To1185WithoutGaps() {
        val ids = repository.getAllIds()
        assertEquals(1185, ids.size)
        val expected = (1..1185).toList()
        assertEquals(expected, ids)
    }

    @Test
    fun testSpecificChunkPages() {
        // chunk 61 is on page 23
        val c61 = repository.getById(61)
        assertNotNull(c61)
        assertEquals(23, c61!!.page)

        // chunk 780 on page 249
        val c780 = repository.getById(780)
        assertNotNull(c780)
        assertEquals(249, c780!!.page)

        // chunk 1134 on page 356
        val c1134 = repository.getById(1134)
        assertNotNull(c1134)
        assertEquals(356, c1134!!.page)
    }

    @Test
    fun testMetaSchemaVersionIs2() {
        val schemaVer = repository.getMetaValue("schema_version")
        assertEquals("2", schemaVer)
    }

    @Test
    fun testChunkTextsSha256MatchesMeta() {
        val metaText = metaFile.readText(Charsets.UTF_8)
        val expectedSha = Regex("\"chunk_texts_sha256\"\\s*:\\s*\"([^\"]+)\"")
            .find(metaText)?.groupValues?.get(1)
        assertNotNull("chunk_texts_sha256 must be present in embeddings_meta.json", expectedSha)

        // Python algorithm copied:
        // hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()
        // where texts are ordered by chunk id: SELECT text FROM chunks ORDER BY id
        println("=== Chunk texts sha256 algorithm copied ===")
        println("Algorithm: MessageDigest.getInstance(\"SHA-256\").digest(texts.joinToString(\"\").toByteArray(Charsets.UTF_8))")
        println("where texts are retrieved with: SELECT text FROM chunks ORDER BY id")

        val texts = repository.getAllChunkTextsOrdered()
        assertEquals(1185, texts.size)

        val md = MessageDigest.getInstance("SHA-256")
        for (text in texts) {
            md.update(text.toByteArray(Charsets.UTF_8))
        }
        val computedSha = md.digest().joinToString("") { "%02x".format(it) }

        println("Expected sha256 (from embeddings_meta.json): $expectedSha")
        println("Computed sha256 (Kotlin SHA-256):            $computedSha")

        assertEquals(expectedSha, computedSha)
    }

    @Test
    fun testGetByIdsPreservesRequestedOrder() {
        val ids = listOf(1134, 61, 780)
        val chunks = repository.getByIds(ids)
        assertEquals(3, chunks.size)
        assertEquals(1134, chunks[0].id)
        assertEquals(61, chunks[1].id)
        assertEquals(780, chunks[2].id)
    }

    @Test
    fun testDisplayTextHasNoPrivateUseOrUnassignedCodePoints() {
        val rows = repository.getAllDisplayTextsOrdered()
        assertEquals(1185, rows.size)
        var changed = 0
        val bad = mutableListOf<String>()
        for ((id, text) in rows) {
            if (text.isEmpty()) bad.add("chunk $id is empty")
            text.codePoints().forEach { cp ->
                val type = Character.getType(cp)
                if (type == Character.PRIVATE_USE.toInt() ||
                    type == Character.UNASSIGNED.toInt() ||
                    type == Character.SURROGATE.toInt()
                ) {
                    bad.add("chunk $id has U+%04X".format(cp))
                }
            }
        }
        for (id in 1..1185) {
            val raw = repository.getById(id)?.text
            val shown = rows[id - 1].second
            if (raw != null && raw != shown) changed++
        }
        println("display_text changed chunks: $changed/${rows.size}")
        assertTrue("display_text bad code points: ${bad.take(10)}", bad.isEmpty())
    }
}
