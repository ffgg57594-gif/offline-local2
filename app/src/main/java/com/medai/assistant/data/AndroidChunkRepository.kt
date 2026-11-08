package com.medai.assistant.data

import android.database.sqlite.SQLiteDatabase
import java.io.File

class AndroidChunkRepository(
    private val dbFile: File
) : ChunkRepository {

    private fun openDb(): SQLiteDatabase {
        return SQLiteDatabase.openDatabase(
            dbFile.absolutePath,
            null,
            SQLiteDatabase.OPEN_READONLY or SQLiteDatabase.NO_LOCALIZED_COLLATORS
        )
    }

    override fun count(): Int {
        val db = openDb()
        try {
            db.rawQuery("SELECT COUNT(*) FROM chunks", null).use { cursor ->
                if (cursor.moveToFirst()) {
                    return cursor.getInt(0)
                }
            }
            return 0
        } finally {
            db.close()
        }
    }

    override fun getById(id: Int): Chunk? {
        val db = openDb()
        try {
            val query = """
                SELECT c.id, b.name, c.page, c.section,
                       c.text, COALESCE(c.display_text, c.text)
                FROM chunks c
                JOIN books b ON b.id = c.book_id
                WHERE c.id = ?
            """.trimIndent()
            db.rawQuery(query, arrayOf(id.toString())).use { cursor ->
                if (cursor.moveToFirst()) {
                    return Chunk(
                        id = cursor.getInt(0),
                        bookName = cursor.getString(1),
                        page = cursor.getInt(2),
                        section = cursor.getString(3) ?: "",
                        text = cursor.getString(4),
                        displayText = cursor.getString(5)
                    )
                }
            }
            return null
        } finally {
            db.close()
        }
    }

    override fun getByIds(ids: List<Int>): List<Chunk> {
        if (ids.isEmpty()) return emptyList()
        val db = openDb()
        try {
            val placeholders = ids.joinToString(",") { "?" }
            val query = """
                SELECT c.id, b.name, c.page, c.section,
                       c.text, COALESCE(c.display_text, c.text)
                FROM chunks c
                JOIN books b ON b.id = c.book_id
                WHERE c.id IN ($placeholders)
            """.trimIndent()
            val args = ids.map { it.toString() }.toTypedArray()
            val results = mutableMapOf<Int, Chunk>()
            db.rawQuery(query, args).use { cursor ->
                while (cursor.moveToNext()) {
                    val chunk = Chunk(
                        id = cursor.getInt(0),
                        bookName = cursor.getString(1),
                        page = cursor.getInt(2),
                        section = cursor.getString(3) ?: "",
                        text = cursor.getString(4),
                        displayText = cursor.getString(5)
                    )
                    results[chunk.id] = chunk
                }
            }
            // Preserve the requested order
            return ids.mapNotNull { results[it] }
        } finally {
            db.close()
        }
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
        val db = openDb()
        try {
            db.rawQuery(query, arrayOf(chunkId.toString(), chunkId.toString())).use { cursor ->
                if (cursor.moveToFirst()) {
                    return Chunk(
                        id = cursor.getInt(0),
                        bookName = cursor.getString(1),
                        page = cursor.getInt(2),
                        section = cursor.getString(3) ?: "",
                        text = cursor.getString(4),
                        displayText = cursor.getString(5)
                    )
                }
            }
            return null
        } finally {
            db.close()
        }
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
        val db = openDb()
        try {
            db.rawQuery(query, arrayOf(chunkId.toString())).use { cursor ->
                if (cursor.moveToFirst()) {
                    return cursor.getInt(0) to cursor.getInt(1)
                }
            }
            return null
        } finally {
            db.close()
        }
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
        val db = openDb()
        try {
            db.rawQuery(query, null).use { cursor ->
                if (cursor.moveToFirst()) {
                    return BookInfo(
                        rawName = cursor.getString(0),
                        pages = cursor.getInt(1),
                        chunks = cursor.getInt(2)
                    )
                }
            }
            return null
        } finally {
            db.close()
        }
    }

    override fun getAllPages(expectedCount: Int): IntArray {
        val db = openDb()
        try {
            val pages = IntArray(expectedCount)
            val query = "SELECT id, page FROM chunks ORDER BY id ASC"
            db.rawQuery(query, null).use { cursor ->
                while (cursor.moveToNext()) {
                    val id = cursor.getInt(0)
                    val page = cursor.getInt(1)
                    if (id in 1..expectedCount) {
                        pages[id - 1] = page
                    }
                }
            }
            return pages
        } finally {
            db.close()
        }
    }
}
