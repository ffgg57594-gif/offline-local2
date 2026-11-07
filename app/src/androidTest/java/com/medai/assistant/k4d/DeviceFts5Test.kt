package com.medai.assistant.k4d

import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * K4d: prove the Android SQLite build really has FTS5, using the packaged
 * 1185-chunk DB and the same MATCH query the app uses.
 */
class DeviceFts5Test {

    @Test
    fun testFts5MatchReturnsRowsOnDeviceSqlite() {
        val rows = DeviceTestRuntime.gateDatabase.matchRowCount("\"heart\"*")
        println("K4d FTS5 MATCH '\"heart\"*' rows=$rows")
        assertTrue("FTS5 MATCH must return at least one row, got $rows", rows > 0)
    }
}
