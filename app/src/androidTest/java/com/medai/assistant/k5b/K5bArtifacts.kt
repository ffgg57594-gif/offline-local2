package com.medai.assistant.k5b

import android.content.Context
import android.graphics.Bitmap
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.io.FileOutputStream

/** Files written by the K5b instrumented tests and pulled by CI. */
object K5bArtifacts {

    fun reportsDir(context: Context): File {
        // Internal app storage: CI pulls it with `adb exec-out run-as`, which
        // always works for this debuggable build even when API 34 scoped
        // storage hides /sdcard/Android/data from the adb shell user.
        val dir = File(context.filesDir, "reports")
        dir.mkdirs()
        return dir
    }

    fun screenshotsDir(context: Context): File {
        val dir = File(context.filesDir, "ui-screenshots")
        dir.mkdirs()
        return dir
    }

    fun screenshotsV3Dir(context: Context): File {
        val dir = File(context.filesDir, "ui-screenshots-v3")
        dir.mkdirs()
        return dir
    }

    fun screenshotsV4Dir(context: Context): File {
        val dir = File(context.filesDir, "ui-screenshots-v4")
        dir.mkdirs()
        return dir
    }

    /** K7a on-device reports (engine stats, native heap growth, downloads). */
    fun k7aReportsDir(context: Context): File {
        val dir = File(context.filesDir, "k7a-reports")
        dir.mkdirs()
        return dir
    }

    fun writeK7aText(context: Context, name: String, text: String) {
        File(k7aReportsDir(context), name).writeText(text, Charsets.UTF_8)
    }

    fun writeText(context: Context, name: String, text: String) {
        File(reportsDir(context), name).writeText(text, Charsets.UTF_8)
    }

    fun screenshotV3(context: Context, name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        Thread.sleep(600)
        val raw: Bitmap = instrumentation.uiAutomation.takeScreenshot()
        try {
            val fileV3 = File(screenshotsV3Dir(context), "$name.png")
            FileOutputStream(fileV3).use { output ->
                raw.compress(Bitmap.CompressFormat.PNG, 100, output)
            }
            val fileV2 = File(screenshotsDir(context), "$name.png")
            FileOutputStream(fileV2).use { output ->
                raw.compress(Bitmap.CompressFormat.PNG, 100, output)
            }
        } finally {
            raw.recycle()
        }
    }

    /**
     * K7a: full-resolution device screenshot (real system bars) written only
     * into files/ui-screenshots-v4. Not copied into the v2 dir so the legacy
     * artifact keeps its fixed 14-file inventory.
     */
    fun screenshotV4(context: Context, name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        Thread.sleep(600)
        val raw: Bitmap = instrumentation.uiAutomation.takeScreenshot()
        val bitmap = if (raw.width > MAX_WIDTH) {
            val height = (raw.height.toLong() * MAX_WIDTH / raw.width).toInt().coerceAtLeast(1)
            Bitmap.createScaledBitmap(raw, MAX_WIDTH, height, true)
        } else {
            raw
        }
        try {
            val file = File(screenshotsV4Dir(context), "$name.png")
            FileOutputStream(file).use { output ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)
            }
        } finally {
            bitmap.recycle()
            if (bitmap !== raw) raw.recycle()
        }
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
