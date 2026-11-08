package com.medai.assistant.k5b

import android.content.Context
import android.graphics.Bitmap
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.io.FileOutputStream

/** Files written by the K5b instrumented tests and pulled by CI. */
object K5bArtifacts {

    fun reportsDir(context: Context): File {
        val dir = context.getExternalFilesDir("reports") ?: context.filesDir
        dir.mkdirs()
        return dir
    }

    fun screenshotsDir(context: Context): File {
        val dir = context.getExternalFilesDir("ui-screenshots") ?: File(context.filesDir, "ui-screenshots")
        dir.mkdirs()
        return dir
    }

    fun writeText(context: Context, name: String, text: String) {
        File(reportsDir(context), name).writeText(text, Charsets.UTF_8)
    }

    /**
     * Full-screen PNG (includes a bottom sheet and the IME when present).
     * Wide emulator screenshots are scaled to [MAX_WIDTH] so the whole
     * `ui-screenshots` artifact stays well under 25 MiB.
     */
    fun screenshot(context: Context, name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        Thread.sleep(350)
        val raw: Bitmap = instrumentation.uiAutomation.takeScreenshot()
        val bitmap = if (raw.width > MAX_WIDTH) {
            val height = (raw.height.toLong() * MAX_WIDTH / raw.width).toInt().coerceAtLeast(1)
            Bitmap.createScaledBitmap(raw, MAX_WIDTH, height, true)
        } else {
            raw
        }
        try {
            val file = File(screenshotsDir(context), "$name.png")
            FileOutputStream(file).use { output ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)
            }
        } finally {
            bitmap.recycle()
            if (bitmap !== raw) raw.recycle()
        }
    }

    private const val MAX_WIDTH = 900
}
