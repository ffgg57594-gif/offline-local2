package com.medai.assistant.ui

/**
 * Test-only UI configuration hook used by the K5b instrumented tests.
 *
 * The values are normally null, so the app follows the system theme and font
 * scale. Instrumented tests set them and recreate the Activity to capture the
 * same screen in light/dark mode and at font scale 1.3 without changing the
 * emulator globally.
 */
object UiOverrides {
    @Volatile
    var forceDark: Boolean? = null

    @Volatile
    var fontScale: Float? = null
}
