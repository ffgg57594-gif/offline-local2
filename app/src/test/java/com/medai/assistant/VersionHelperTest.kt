package com.medai.assistant

import org.junit.Assert.assertEquals
import org.junit.Test

class VersionHelperTest {
    @Test
    fun versionName_isNotEmpty() {
        assertEquals("1.0.0", VersionHelper.versionName())
    }
}
