package com.medai.assistant.ui

import android.os.Debug
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.medai.assistant.data.ChunkRepository
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.llm.BigCores
import com.medai.assistant.llm.LlamaEngine
import com.medai.assistant.runtime.AppGraph
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale

/**
 * K7a: debug-only "LLM test" screen (long-press the app title -> debug
 * screen -> اختبار الموديل). Not part of the normal user flow; there is no
 * Explain button or chat integration in this stage.
 *
 * Shows the installed model status, load time, three fixed test prompts
 * (short, ~300 tokens, ~700 tokens built from real chunk text), streaming
 * generation with Stop, per-run stats (prompt tokens, time to first token,
 * tokens/sec, peak PSS, thermal status), and a Copy report button.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LlmTestScreen(onBack: () -> Unit) {
    val context = LocalContext.current.applicationContext
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()
    val manager = AppGraph.modelManager(context)

    val modelFile: File? = remember { manager.anyInstalledFile() }

    var engine by remember { mutableStateOf<LlamaEngine?>(null) }
    var loading by remember { mutableStateOf(false) }
    var loadProgress by remember { mutableStateOf(0f) }
    var loadError by remember { mutableStateOf<String?>(null) }

    var generating by remember { mutableStateOf(false) }
    var output by remember { mutableStateOf("") }
    var lastStats by remember { mutableStateOf<LlamaEngine.GenerationResult?>(null) }
    var peakPssKb by remember { mutableStateOf(0L) }
    var thermalStatus by remember { mutableStateOf("غير متاح") }
    var promptIndex by remember { mutableStateOf(0) }

    val prompts = remember {
        buildTestPrompts(AppGraph.currentResources()?.repository)
    }

    var pssSampler by remember { mutableStateOf<Job?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            // Leaving the screen cancels the sampler and frees the native
            // model; free() is safe even while a generation is running.
            pssSampler?.cancel()
            engine?.free()
        }
    }

    fun startPssSampler() {
        peakPssKb = readTotalPssKb()
        pssSampler?.cancel()
        pssSampler = scope.launch {
            while (true) {
                val sampled = withContext(Dispatchers.IO) {
                    runCatching { readTotalPssKb() }.getOrDefault(peakPssKb)
                }
                if (sampled > peakPssKb) peakPssKb = sampled
                thermalStatus = readThermalStatus(context)
                delay(250)
            }
        }
    }

    fun stopPssSampler() {
        pssSampler?.cancel()
        pssSampler = null
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "اختبار الموديل (LLM)",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        fontFamily = DesignFonts.ArabicUiFamily
                    )
                },
                navigationIcon = {
                    TextButton(onClick = onBack, modifier = Modifier.heightIn(min = 48.dp)) {
                        Text("رجوع", fontFamily = DesignFonts.ArabicUiFamily)
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // Model status ------------------------------------------------
            Text(
                if (modelFile != null) {
                    "الموديل المثبت: ${modelFile.name} " +
                        "(${modelFile.length() / (1024 * 1024)} ميجابايت)"
                } else {
                    "لا يوجد موديل مثبت — نزّله من الإعدادات (قسم الموديل)."
                },
                modifier = Modifier.testTag("llm_test_model_status"),
                style = MaterialTheme.typography.bodyLarge,
                fontFamily = DesignFonts.ArabicUiFamily,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface
            )
            engine?.let { current ->
                Text(
                    "تم التحميل في ${current.loadMs} م ث — ${current.modelInfo.desc} " +
                        "(n_ctx=${current.modelInfo.nCtx}، قالب محادثة: " +
                        "${if (current.modelInfo.hasChatTemplate) current.modelInfo.template else "لا يوجد"})",
                    modifier = Modifier.testTag("llm_test_model_info"),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            loadError?.let { message ->
                Text(
                    message,
                    modifier = Modifier.testTag("llm_test_load_error"),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.error
                )
            }

            // Load --------------------------------------------------------
            if (engine == null) {
                if (loading) {
                    LinearProgressIndicator(
                        progress = { loadProgress },
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("llm_test_load_progress")
                    )
                    Text(
                        "تحميل الموديل... ${(loadProgress * 100).toInt()}%",
                        modifier = Modifier.testTag("llm_test_load_status"),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = DesignFonts.ArabicUiFamily
                    )
                    OutlinedButton(
                        onClick = { LlamaEngine.loadCancelRequested = true },
                        modifier = Modifier.testTag("llm_test_cancel_load")
                    ) {
                        Text("إلغاء التحميل", fontFamily = DesignFonts.ArabicUiFamily)
                    }
                } else if (modelFile != null) {
                    Button(
                        onClick = {
                            loading = true
                            loadError = null
                            loadProgress = 0f
                            scope.launch {
                                try {
                                    engine = LlamaEngine.load(
                                        path = modelFile.absolutePath,
                                        nCtx = LlamaEngine.DEFAULT_N_CTX,
                                        nBatch = LlamaEngine.DEFAULT_N_BATCH,
                                        nThreads = BigCores.count()
                                    ) { fraction -> loadProgress = fraction }
                                    loadError = null
                                } catch (failure: Throwable) {
                                    loadError = "فشل التحميل: ${failure.message}"
                                } finally {
                                    loading = false
                                }
                            }
                        },
                        enabled = modelFile != null,
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp)
                            .testTag("llm_test_load")
                    ) {
                        Text(
                            "تحميل الموديل ( mmap، أنوية كبيرة: ${BigCores.count()} )",
                            fontFamily = DesignFonts.ArabicUiFamily,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }

            // Prompts -----------------------------------------------------
            if (engine != null) {
                Text(
                    "البرومبتات الثابتة:",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    fontFamily = DesignFonts.ArabicUiFamily
                )
                prompts.forEachIndexed { index, prompt ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        RadioButton(
                            selected = promptIndex == index,
                            onClick = { promptIndex = index },
                            modifier = Modifier.testTag("llm_test_prompt_${prompt.tag}")
                        )
                        Column {
                            Text(
                                prompt.title,
                                fontWeight = FontWeight.Bold,
                                fontFamily = DesignFonts.ArabicUiFamily
                            )
                            Text(
                                "${prompt.approxTokens} توكن تقريباً — ${prompt.source}",
                                style = MaterialTheme.typography.bodySmall,
                                fontFamily = DesignFonts.ArabicUiFamily,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }

                // Generate / Stop -----------------------------------------
                if (generating) {
                    Button(
                        onClick = { engine?.cancel() },
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp)
                            .testTag("llm_test_stop")
                    ) {
                        Text("إيقاف", fontFamily = DesignFonts.ArabicUiFamily, fontWeight = FontWeight.Bold)
                    }
                } else {
                    Button(
                        onClick = {
                            val activeEngine = engine ?: return@Button
                            generating = true
                            output = ""
                            lastStats = null
                            startPssSampler()
                            scope.launch {
                                try {
                                    val result = activeEngine.generate(
                                        prompt = prompts[promptIndex].text,
                                        maxTokens = 128
                                    ) { piece -> output += piece }
                                    lastStats = result
                                } catch (failure: Throwable) {
                                    output += "\n[خطأ: ${failure.message}]"
                                } finally {
                                    generating = false
                                    stopPssSampler()
                                }
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp)
                            .testTag("llm_test_generate")
                    ) {
                        Text("توليد", fontFamily = DesignFonts.ArabicUiFamily, fontWeight = FontWeight.Bold)
                    }
                }
            }

            // Output ------------------------------------------------------
            if (output.isNotEmpty()) {
                Text(
                    output,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 120.dp)
                        .testTag("llm_test_output"),
                    style = MaterialTheme.typography.bodyMedium,
                    fontFamily = DesignFonts.ArabicUiFamily
                )
            }

            // Stats -------------------------------------------------------
            lastStats?.let { result ->
                val stats = result.stats
                Text(
                    buildString {
                        append("توكنات الموجه: ${stats.promptTokens}")
                        append(" — زمن أول توكن: ${stats.timeToFirstTokenMs} م ث")
                        append(" — ${String.format(Locale.US, "%.1f", stats.tokensPerSecond)} توكن/ثانية")
                        append("\nتوكنات المخرَج: ${stats.outputTokens}")
                        append(" — الزمن الكلي: ${stats.totalMs} م ث")
                        append(if (result.completed) " — اكتمل" else " — أُلغي")
                        append("\nذروة PSS: ${peakPssKb} كيلوبايت — الحالة الحرارية: $thermalStatus")
                    },
                    modifier = Modifier.testTag("llm_test_stats"),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            // Copy report -------------------------------------------------
            if (engine != null) {
                OutlinedButton(
                    onClick = {
                        val report = buildReport(
                            modelFile = modelFile,
                            engine = engine,
                            result = lastStats,
                            prompt = prompts[promptIndex],
                            output = output,
                            peakPssKb = peakPssKb,
                            thermalStatus = thermalStatus
                        )
                        clipboard.setText(AnnotatedString(report))
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .testTag("llm_test_copy_report")
                ) {
                    Text("نسخ التقرير", fontFamily = DesignFonts.ArabicUiFamily, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

private data class TestPrompt(
    val tag: String,
    val title: String,
    val approxTokens: Int,
    val source: String,
    val text: String
)

/**
 * Three fixed prompts: a short question, a ~300-token passage and a
 * ~700-token passage, both built from real knowledge-base chunk text so
 * the timing numbers reflect the real workload.
 */
private fun buildTestPrompts(repository: ChunkRepository?): List<TestPrompt> {
    val short = "Summarize the most common causes of abnormal uterine bleeding."
    val mediumSource = repository?.getById(60)?.text
    val longSource = repository?.getById(61)?.text
    val medium = mediumSource?.take(1200)
        ?: "Abnormal uterine bleeding is one of the most common reasons women consult a gynecologist. "
    val long = longSource?.take(2800)
        ?: (medium + " The evaluation includes a detailed history, physical examination, laboratory "
            + "testing and imaging. Management depends on the underlying cause. ")
    return listOf(
        TestPrompt(
            tag = "short",
            title = "قصير",
            approxTokens = short.length / 4,
            source = "سؤال ثابت",
            text = short
        ),
        TestPrompt(
            tag = "medium",
            title = "متوسط (~300 توكن)",
            approxTokens = medium.length / 4,
            source = if (mediumSource != null) "نص chunk حقيقي" else "نص بديل",
            text = medium
        ),
        TestPrompt(
            tag = "long",
            title = "طويل (~700 توكن)",
            approxTokens = long.length / 4,
            source = if (longSource != null) "نص chunk حقيقي" else "نص بديل",
            text = long
        )
    )
}

private fun readTotalPssKb(): Long {
    val info = Debug.MemoryInfo()
    return runCatching {
        Debug.getMemoryInfo(info)
        info.totalPss.toLong()
    }.getOrDefault(0L)
}

private fun readThermalStatus(context: android.content.Context): String {
    // Reflection keeps lintVital happy about API levels; the constants are
    // compile-time inlined so no runtime dependency on newer APIs is added.
    return runCatching {
        val powerManager =
            context.getSystemService(android.content.Context.POWER_SERVICE) as? android.os.PowerManager
                ?: return "غير متاح"
        val status = android.os.PowerManager::class.java
            .getMethod("getCurrentThermalStatus")
            .invoke(powerManager) as Int
        when (status) {
            android.os.PowerManager.THERMAL_STATUS_NONE -> "طبيعي"
            android.os.PowerManager.THERMAL_STATUS_LIGHT -> "خفيف"
            android.os.PowerManager.THERMAL_STATUS_MODERATE -> "متوسط"
            android.os.PowerManager.THERMAL_STATUS_SEVERE -> "شديد"
            android.os.PowerManager.THERMAL_STATUS_CRITICAL -> "حرج"
            android.os.PowerManager.THERMAL_STATUS_EMERGENCY,
            android.os.PowerManager.THERMAL_STATUS_SHUTDOWN -> "طارئ"
            else -> "غير معروف ($status)"
        }
    }.getOrDefault("غير متاح")
}

private fun buildReport(
    modelFile: File?,
    engine: LlamaEngine?,
    result: LlamaEngine.GenerationResult?,
    prompt: TestPrompt,
    output: String,
    peakPssKb: Long,
    thermalStatus: String
): String = buildString {
    appendLine("LLM test report (K7a debug)")
    appendLine("model file: ${modelFile?.name ?: "none"} (${modelFile?.length() ?: 0} bytes)")
    if (engine != null) {
        appendLine("desc: ${engine.modelInfo.desc}")
        appendLine("size: ${engine.modelInfo.sizeBytes} bytes")
        appendLine("n_ctx: ${engine.modelInfo.nCtx} (train ${engine.modelInfo.nCtxTrain})")
        appendLine("n_vocab: ${engine.modelInfo.nVocab}")
        appendLine("chat template: ${if (engine.modelInfo.hasChatTemplate) engine.modelInfo.template else "none"}")
        appendLine("threads: ${engine.nThreads}, load ms: ${engine.loadMs}")
    }
    appendLine("prompt: ${prompt.tag} (~${prompt.approxTokens} tokens, ${prompt.source})")
    if (result != null) {
        appendLine("prompt tokens: ${result.stats.promptTokens}")
        appendLine("time to first token ms: ${result.stats.timeToFirstTokenMs}")
        appendLine("tokens/sec: ${String.format(Locale.US, "%.2f", result.stats.tokensPerSecond)}")
        appendLine("output tokens: ${result.stats.outputTokens}, total ms: ${result.stats.totalMs}")
        appendLine("completed: ${result.completed}")
    } else {
        appendLine("no generation run yet")
    }
    appendLine("peak PSS kb: $peakPssKb")
    appendLine("thermal: $thermalStatus")
    appendLine("--- output ---")
    appendLine(output)
}
