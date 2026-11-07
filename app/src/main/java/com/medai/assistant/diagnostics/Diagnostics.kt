package com.medai.assistant.diagnostics

import android.content.Context
import android.os.Build
import com.medai.assistant.BuildConfig
import com.medai.assistant.SearchTiming
import java.io.PrintWriter
import java.io.StringWriter
import java.util.ArrayDeque

/**
 * Process-wide diagnostics recorder used by the "نسخ تقرير التشخيص" action.
 *
 * It deliberately keeps only the last five caught exceptions and clips every
 * stack trace to 3000 characters so the copied report stays small enough for a
 * clipboard on low-memory devices.
 */
object Diagnostics {
    private const val MAX_EXCEPTIONS = 5
    private const val MAX_STACK_CHARS = 3000
    private const val FALLBACK_ORT_VERSION = "1.18.0"

    private val exceptions = ArrayDeque<String>()

    @Volatile
    var installStatus: String = "not started"

    @Volatile
    var assetHashCheck: String = "not run"

    @Volatile
    var modelLoadMs: Long = -1L

    @Volatile
    var lastTimings: SearchTiming? = null

    @Volatile
    var lastQuestion: String = ""

    @Synchronized
    fun recordException(t: Throwable) {
        val writer = StringWriter()
        t.printStackTrace(PrintWriter(writer))
        val full = "${t.javaClass.name}: ${t.message ?: "(no message)"}\n${writer}"
        val entry = if (full.length > MAX_STACK_CHARS) {
            full.substring(0, MAX_STACK_CHARS) + "\n… (clipped at 3000 characters)"
        } else {
            full
        }
        exceptions.addFirst(entry)
        while (exceptions.size > MAX_EXCEPTIONS) {
            exceptions.removeLast()
        }
    }

    @Synchronized
    fun exceptionCount(): Int = exceptions.size

    @Synchronized
    fun exceptionsSnapshot(): List<String> = exceptions.toList()

    fun recordTimings(question: String, timings: SearchTiming) {
        lastQuestion = question
        lastTimings = timings
    }

    /**
     * `OrtEnvironment.getVersion()` exists in onnxruntime 1.18, but reflection
     * keeps the report usable on older AARs that do not expose it.
     */
    fun onnxRuntimeVersion(): String {
        return try {
            val cls = Class.forName("ai.onnxruntime.OrtEnvironment")
            val version = cls.getMethod("getVersion").invoke(null) as? String
            version?.takeIf { it.isNotBlank() } ?: FALLBACK_ORT_VERSION
        } catch (_: Throwable) {
            FALLBACK_ORT_VERSION
        }
    }

    fun buildReport(context: Context): String {
        val sb = StringBuilder()
        sb.appendLine("تقرير تشخيص MedAI")
        sb.appendLine("=====================")
        @Suppress("DEPRECATION")
        val versionCode = context.packageManager
            .getPackageInfo(context.packageName, 0)
            .versionCode
        sb.appendLine("app_version=${BuildConfig.VERSION_NAME} ($versionCode)")
        sb.appendLine("build_time=${BuildConfig.BUILD_TIME}")
        sb.appendLine("android_release=${Build.VERSION.RELEASE}")
        sb.appendLine("android_api=${Build.VERSION.SDK_INT}")
        sb.appendLine("device_manufacturer=${Build.MANUFACTURER}")
        sb.appendLine("device_model=${Build.MODEL}")
        sb.appendLine("device=${Build.MANUFACTURER} ${Build.MODEL}")
        sb.appendLine("abi=${Build.SUPPORTED_ABIS.joinToString(", ")}")
        sb.appendLine("onnxruntime=${onnxRuntimeVersion()}")
        sb.appendLine("install_status=$installStatus")
        sb.appendLine("asset_hash_check=$assetHashCheck")
        sb.appendLine("model_load_ms=$modelLoadMs")

        val timings = lastTimings
        if (timings == null) {
            sb.appendLine("last_question_timings=not run")
        } else {
            sb.appendLine("last_question=${lastQuestion.replace('\n', ' ')}")
            sb.appendLine("last_tokenize_ms=${timings.tokenizeMs}")
            sb.appendLine("last_embed_ms=${timings.embedMs}")
            sb.appendLine("last_search_ms=${timings.searchMs}")
            if (timings.gateSignalsMs >= 0) {
                sb.appendLine("last_gate_signals_ms=${timings.gateSignalsMs}")
            }
            sb.appendLine("last_total_ms=${timings.totalMs}")
        }

        val caught = exceptionsSnapshot()
        sb.appendLine("caught_exceptions=${caught.size}")
        if (caught.isEmpty()) {
            sb.appendLine("(none)")
        } else {
            caught.forEachIndexed { index, entry ->
                sb.appendLine("--- exception ${index + 1} ---")
                sb.appendLine(entry)
            }
        }
        return sb.toString()
    }
}
