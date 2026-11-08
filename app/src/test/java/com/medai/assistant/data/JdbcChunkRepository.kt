package com.medai.assistant.data

import java.io.File
import java.sql.Connection
import java.sql.DriverManager

class JdbcChunkRepository(
    private val dbFile: File
) : ChunkRepository {

    init {
        Class.forName("org.sqlite.JDBC")
    }

    private fun getConnection(): Connection {
        return DriverManager.getConnection("jdbc:sqlite:${dbFile.absolutePath}")
    }

    override fun count(): Int {
        getConnection().use { conn ->
            conn.createStatement().use { stmt ->
                stmt.executeQuery("SELECT COUNT(*) FROM chunks").use { rs ->
                    if (rs.next()) {
                        return rs.getInt(1)
                    }
                }
            }
        }
        return 0
    }

    override fun getById(id: Int): Chunk? {
        val query = """
            SELECT c.id, b.name, c.page, c.section,
                   c.text, COALESCE(c.display_text, c.text)
            FROM chunks c
            JOIN books b ON b.id = c.book_id
            WHERE c.id = ?
        """.trimIndent()

        getConnection().use { conn ->
            conn.prepareStatement(query).use { stmt ->
                stmt.setInt(1, id)
                stmt.executeQuery().use { rs ->
                    if (rs.next()) {
                        return Chunk(
                            id = rs.getInt(1),
                            bookName = rs.getString(2),
                            page = rs.getInt(3),
                            section = rs.getString(4) ?: "",
                            text = rs.getString(5),
                            displayText = rs.getString(6)
                        )
                    }
                }
            }
        }
        return null
    }

    override fun getByIds(ids: List<Int>): List<Chunk> {
        if (ids.isEmpty()) return emptyList()
        val placeholders = ids.joinToString(",") { "?" }
        val query = """
            SELECT c.id, b.name, c.page, c.section,
                   c.text, COALESCE(c.display_text, c.text)
            FROM chunks c
            JOIN books b ON b.id = c.book_id
            WHERE c.id IN ($placeholders)
        """.trimIndent()

        val results = mutableMapOf<Int, Chunk>()
        getConnection().use { conn ->
            conn.prepareStatement(query).use { stmt ->
                for (i in ids.indices) {
                    stmt.setInt(i + 1, ids[i])
                }
                stmt.executeQuery().use { rs ->
                    while (rs.next()) {
                        val chunk = Chunk(
                            id = rs.getInt(1),
                            bookName = rs.getString(2),
                            page = rs.getInt(3),
                            section = rs.getString(4) ?: "",
                            text = rs.getString(5),
                            displayText = rs.getString(6)
                        )
                        results[chunk.id] = chunk
                    }
                }
            }
        }
        return ids.mapNotNull { results[it] }
    }

    override fun getNeighbour(chunkId: Int, delta: Int): Chunk? {
        if (delta == 0) return getById(chunkId)
        val comparison = if (delta > 0) ">" else "<"
        val order = if (delta > 0) "ASC" else "DESC"
        val query = """
            SELECT c.id, b.name, c.page, c.section,
                   c.text, COALESCE(c.display_text, c.text)
            FROM chunks c
            JOIN books b ON b.id = c.book_id
            WHERE c.book_id = (SELECT book_id FROM chunks WHERE id = ?)
              AND c.id $comparison ?
            ORDER BY c.id $order
            LIMIT 1
        """.trimIndent()
        getConnection().use { conn ->
            conn.prepareStatement(query).use { stmt ->
                stmt.setInt(1, chunkId)
                stmt.setInt(2, chunkId)
                stmt.executeQuery().use { rs ->
                    if (rs.next()) {
                        return Chunk(
                            id = rs.getInt(1),
                            bookName = rs.getString(2),
                            page = rs.getInt(3),
                            section = rs.getString(4) ?: "",
                            text = rs.getString(5),
                            displayText = rs.getString(6)
                        )
                    }
                }
            }
        }
        return null
    }

    override fun getPositionInBook(chunkId: Int): Pair<Int, Int>? {
        val query = """
            SELECT
              (SELECT COUNT(*) FROM chunks x
                 WHERE x.book_id = c.book_id AND x.id <= c.id) AS position,
              (SELECT COUNT(*) FROM chunks x WHERE x.book_id = c.book_id) AS total
            FROM chunks c
            WHERE c.id = ?
        """.trimIndent()
        getConnection().use { conn ->
            conn.prepareStatement(query).use { stmt ->
                stmt.setInt(1, chunkId)
                stmt.executeQuery().use { rs ->
                    if (rs.next()) {
                        return rs.getInt(1) to rs.getInt(2)
                    }
                }
            }
        }
        return null
    }

    override fun primaryBook(): BookInfo? {
        val query = """
            SELECT b.name, b.pages, COUNT(c.id)
            FROM books b
            LEFT JOIN chunks c ON c.book_id = b.id
            GROUP BY b.id
            ORDER BY b.id
            LIMIT 1
        """.trimIndent()
        getConnection().use { conn ->
            conn.createStatement().use { stmt ->
                stmt.executeQuery(query).use { rs ->
                    if (rs.next()) {
                        return BookInfo(
                            rawName = rs.getString(1),
                            pages = rs.getInt(2),
                            chunks = rs.getInt(3)
                        )
                    }
                }
            }
        }
        return null
    }

    override fun getAllPages(expectedCount: Int): IntArray {
        val pages = IntArray(expectedCount)
        val query = "SELECT id, page FROM chunks ORDER BY id ASC"
        getConnection().use { conn ->
            conn.createStatement().use { stmt ->
                stmt.executeQuery(query).use { rs ->
                    while (rs.next()) {
                        val id = rs.getInt(1)
                        val page = rs.getInt(2)
                        if (id in 1..expectedCount) {
                            pages[id - 1] = page
                        }
                    }
                }
            }
        }
        return pages
    }

    fun getAllChunkTextsOrdered(): List<String> {
        val list = mutableListOf<String>()
        getConnection().use { conn ->
            conn.createStatement().use { stmt ->
                stmt.executeQuery("SELECT text FROM chunks ORDER BY id").use { rs ->
                    while (rs.next()) {
                        list.add(rs.getString(1))
                    }
                }
            }
        }
        return list
    }

    fun getAllIds(): List<Int> {
        val list = mutableListOf<Int>()
        getConnection().use { conn ->
            conn.createStatement().use { stmt ->
                stmt.executeQuery("SELECT id FROM chunks ORDER BY id").use { rs ->
                    while (rs.next()) {
                        list.add(rs.getInt(1))
                    }
                }
            }
        }
        return list
    }

    fun getMetaValue(key: String): String? {
        getConnection().use { conn ->
            conn.prepareStatement("SELECT value FROM meta WHERE key = ?").use { stmt ->
                stmt.setString(1, key)
                stmt.executeQuery().use { rs ->
                    if (rs.next()) {
                        return rs.getString(1)
                    }
                }
            }
        }
        return null
    }

    fun getAllDisplayTextsOrdered(): List<Pair<Int, String>> {
        val list = mutableListOf<Pair<Int, String>>()
        getConnection().use { conn ->
            conn.createStatement().use { stmt ->
                stmt.executeQuery(
                    "SELECT id, COALESCE(display_text, text) FROM chunks ORDER BY id"
                ).use { rs ->
                    while (rs.next()) {
                        list.add(rs.getInt(1) to rs.getString(2))
                    }
                }
            }
        }
        return list
    }
}
