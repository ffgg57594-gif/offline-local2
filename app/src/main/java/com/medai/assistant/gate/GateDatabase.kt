package com.medai.assistant.gate

import android.database.Cursor
import org.sqlite.database.sqlite.SQLiteDatabase
import java.io.Closeable
import java.io.File
import java.sql.Connection
import java.sql.DriverManager

/**
 * Read-only access to the FTS5 index plus the FTS5 porter stem helper.
 *
 * Implementations must use exactly the index tokenizer:
 * `porter unicode61 remove_diacritics 2`.
 */
interface GateDatabase : Closeable {
    /** Stem one token with the same FTS5 porter tokenizer as the index. */
    fun stem(token: String): String

    /** Number of chunks whose search_text contains [stem] (prefix MATCH). */
    fun docFreq(stem: String): Int

    /** True when [chunkId]'s search_text contains [stem] (prefix MATCH). */
    fun chunkContainsStem(chunkId: Int, stem: String): Boolean

    /** Raw `chunks_fts MATCH ?` row count, used by the on-device FTS5 check. */
    fun matchRowCount(query: String): Int
}

/** JVM-only implementation used by `testDebugUnitTest` (org.xerial:sqlite-jdbc). */
class JdbcGateDatabase(dbFile: File) : GateDatabase {
    private val db: Connection
    private val stemDb: Connection
    private val stemCache = HashMap<String, String>()
    private val dfCache = HashMap<String, Int>()

    init {
        Class.forName("org.sqlite.JDBC")
        db = DriverManager.getConnection("jdbc:sqlite:${dbFile.absolutePath}")
        stemDb = DriverManager.getConnection("jdbc:sqlite::memory:")
        stemDb.createStatement().use { statement ->
            statement.execute(
                "CREATE VIRTUAL TABLE gate_stem_helper USING fts5(x, tokenize='porter unicode61 remove_diacritics 2')"
            )
            statement.execute(
                "CREATE VIRTUAL TABLE gate_stem_vocab USING fts5vocab(gate_stem_helper, 'col')"
            )
        }
    }

    @Synchronized
    override fun stem(token: String): String {
        stemCache[token]?.let { return it }
        stemDb.createStatement().use { statement ->
            statement.executeUpdate("DELETE FROM gate_stem_helper")
        }
        stemDb.prepareStatement("INSERT INTO gate_stem_helper(rowid, x) VALUES (1, ?)").use { statement ->
            statement.setString(1, token)
            statement.executeUpdate()
        }
        var result = token
        stemDb.createStatement().use { statement ->
            statement.executeQuery("SELECT term FROM gate_stem_vocab").use { rs ->
                if (rs.next()) {
                    result = rs.getString(1)
                }
            }
        }
        stemCache[token] = result
        return result
    }

    @Synchronized
    override fun docFreq(stem: String): Int {
        dfCache[stem]?.let { return it }
        val count = try {
            db.prepareStatement("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?").use { statement ->
                statement.setString(1, "\"$stem\"*")
                statement.executeQuery().use { rs ->
                    if (rs.next()) rs.getInt(1) else 0
                }
            }
        } catch (_: Exception) {
            0
        }
        dfCache[stem] = count
        return count
    }

    @Synchronized
    override fun chunkContainsStem(chunkId: Int, stem: String): Boolean {
        return try {
            db.prepareStatement(
                "SELECT COUNT(*) FROM chunks_fts WHERE rowid = ? AND chunks_fts MATCH ?"
            ).use { statement ->
                statement.setInt(1, chunkId)
                statement.setString(2, "\"$stem\"*")
                statement.executeQuery().use { rs ->
                    rs.next() && rs.getInt(1) > 0
                }
            }
        } catch (_: Exception) {
            false
        }
    }

    @Synchronized
    override fun matchRowCount(query: String): Int {
        return db.prepareStatement("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?").use { statement ->
            statement.setString(1, query)
            statement.executeQuery().use { rs ->
                if (rs.next()) rs.getInt(1) else 0
            }
        }
    }

    @Synchronized
    override fun close() {
        try {
            db.close()
        } finally {
            stemDb.close()
        }
    }
}

/**
 * On-device implementation.
 *
 * `io.requery:sqlite-android` is no longer resolvable from Maven Central or
 * JCenter, so this uses the Maven Central SQLite Android Bindings artifact
 * `mil.nga:sqlite-android:3450200`. Its `libsqliteX.so` is compiled with FTS5
 * and the porter tokenizer (verified in CI).
 */
class AndroidGateDatabase(dbFile: File) : GateDatabase {
    private val db: SQLiteDatabase
    private val stemDb: SQLiteDatabase
    private val stemCache = HashMap<String, String>()
    private val dfCache = HashMap<String, Int>()

    private companion object {
        /**
         * SQLite Android Bindings ship FTS5 in `libsqliteX.so`, but the AAR
         * does not load it automatically. `System.loadLibrary` must run before
         * the first SQLite call; `lazy` makes it happen exactly once.
         */
        val nativeLoaded: Boolean by lazy {
            System.loadLibrary("sqliteX")
            true
        }
    }

    init {
        check(nativeLoaded)
        db = SQLiteDatabase.openDatabase(
            dbFile.absolutePath,
            null,
            SQLiteDatabase.OPEN_READONLY or SQLiteDatabase.NO_LOCALIZED_COLLATORS
        )
        stemDb = SQLiteDatabase.create(null as SQLiteDatabase.CursorFactory?)
        stemDb.execSQL(
            "CREATE VIRTUAL TABLE gate_stem_helper USING fts5(x, tokenize='porter unicode61 remove_diacritics 2')"
        )
        stemDb.execSQL(
            "CREATE VIRTUAL TABLE gate_stem_vocab USING fts5vocab(gate_stem_helper, 'col')"
        )
    }

    @Synchronized
    override fun stem(token: String): String {
        stemCache[token]?.let { return it }
        stemDb.execSQL("DELETE FROM gate_stem_helper")
        stemDb.execSQL(
            "INSERT INTO gate_stem_helper(rowid, x) VALUES (1, ?)",
            arrayOf<Any?>(token)
        )
        var result = token
        val cursor: Cursor = stemDb.rawQuery("SELECT term FROM gate_stem_vocab", null)
        try {
            if (cursor.moveToFirst()) {
                result = cursor.getString(0)
            }
        } finally {
            cursor.close()
        }
        stemCache[token] = result
        return result
    }

    @Synchronized
    override fun docFreq(stem: String): Int {
        dfCache[stem]?.let { return it }
        val count = try {
            val cursor = db.rawQuery(
                "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
                arrayOf("\"$stem\"*")
            )
            try {
                if (cursor.moveToFirst()) cursor.getInt(0) else 0
            } finally {
                cursor.close()
            }
        } catch (_: Exception) {
            0
        }
        dfCache[stem] = count
        return count
    }

    @Synchronized
    override fun chunkContainsStem(chunkId: Int, stem: String): Boolean {
        return try {
            val cursor = db.rawQuery(
                "SELECT COUNT(*) FROM chunks_fts WHERE rowid = ? AND chunks_fts MATCH ?",
                arrayOf(chunkId.toString(), "\"$stem\"*")
            )
            try {
                cursor.moveToFirst() && cursor.getInt(0) > 0
            } finally {
                cursor.close()
            }
        } catch (_: Exception) {
            false
        }
    }

    @Synchronized
    override fun matchRowCount(query: String): Int {
        val cursor = db.rawQuery(
            "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
            arrayOf(query)
        )
        try {
            return if (cursor.moveToFirst()) cursor.getInt(0) else 0
        } finally {
            cursor.close()
        }
    }

    @Synchronized
    override fun close() {
        try {
            db.close()
        } finally {
            stemDb.close()
        }
    }
}
