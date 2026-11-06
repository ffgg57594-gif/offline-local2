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
                SELECT c.id, b.name, c.page, c.section, c.text
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
                        text = cursor.getString(4)
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
                SELECT c.id, b.name, c.page, c.section, c.text
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
                        text = cursor.getString(4)
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
