package com.medai.assistant.ui

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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.medai.assistant.SearchTiming
import com.medai.assistant.data.Chunk
import com.medai.assistant.data.InstallState
import com.medai.assistant.diagnostics.Diagnostics
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.gate.GateDecision
import com.medai.assistant.gate.GateSignals
import com.medai.assistant.runtime.AppGraph
import com.medai.assistant.runtime.AppRuntimeState
import com.medai.assistant.runtime.LoadedResources
import com.medai.assistant.search.SearchResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale

private data class DebugHit(
    val hit: SearchResult,
    val chunk: Chunk?
)

private data class DebugSearchState(
    val preset: String,
    val s1: Double,
    val s3: Double,
    val s4: Int,
    val accepted: Boolean,
    val stems: List<String>,
    val hits: List<DebugHit>,
    val timings: SearchTiming
)

private data class StageStats(
    val name: String,
    val p50Ms: Long,
    val p95Ms: Long,
    val maxMs: Long
)

private data class DebugBenchmark(
    val runs: Int,
    val stages: List<StageStats>,
    val total: StageStats,
    val warmupMs: Long
)

private val DEBUG_QUESTIONS = listOf(
    "What are the symptoms and emergency treatment of acute myocardial infarction?",
    "How is acute appendicitis diagnosed in adults?",
    "What are the diagnostic criteria for type 2 diabetes mellitus?",
    "What is the first-line treatment for uncomplicated community-acquired pneumonia?",
    "How does bacterial meningitis present clinically in children?",
    "What are the major complications of chronic kidney disease stage 4?",
    "What is the management of status epilepticus in the emergency department?",
    "How is pulmonary embolism diagnosed using clinical scores and imaging?",
    "What are the treatment options for primary hypertension?",
    "What are the signs and initial treatment of anaphylaxis?"
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebugScreen(onBack: () -> Unit) {
    val runtime by AppGraph.runtimeState.collectAsState()
    val install by AppGraph.installState.collectAsState()

    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current

    var question by remember {
        mutableStateOf("What are the symptoms and emergency treatment of acute myocardial infarction?")
    }
    var preset by remember { mutableStateOf("balanced") }
    var searching by remember { mutableStateOf(false) }
    var searchState by remember { mutableStateOf<DebugSearchState?>(null) }
    var searchError by remember { mutableStateOf<String?>(null) }
    var ftsRows by remember { mutableStateOf<Int?>(null) }
    var ftsError by remember { mutableStateOf<String?>(null) }
    var benchmarking by remember { mutableStateOf(false) }
    var benchmark by remember { mutableStateOf<DebugBenchmark?>(null) }
    var benchmarkStatus by remember { mutableStateOf<String?>(null) }

    val resources = (runtime as? AppRuntimeState.Ready)?.resources
    val ready = resources != null

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("MedAI Debug / K5a") },
                navigationIcon = {
                    TextButton(onClick = onBack, modifier = Modifier.heightIn(min = 48.dp)) {
                        Text("رجوع")
                    }
                },
                actions = {
                    TextButton(
                        onClick = {
                            val report = try {
                                Diagnostics.buildReport(context)
                            } catch (failure: Throwable) {
                                Diagnostics.recordException(failure)
                                "تعذّر إنشاء تقرير التشخيص: " +
                                    (failure.message ?: failure.javaClass.simpleName)
                            }
                            clipboard.setText(AnnotatedString(report))
                        },
                        modifier = Modifier.heightIn(min = 48.dp)
                    ) {
                        Text("نسخ التشخيص")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                    titleContentColor = MaterialTheme.colorScheme.onPrimaryContainer
                )
            )
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Text(
                        "Runtime",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                    Text("CPU cores: ${Runtime.getRuntime().availableProcessors()}")
                    when (val state = install) {
                        is InstallState.Idle -> Text("Install: idle")
                        is InstallState.Copying -> {
                            val fraction = if (state.totalBytes > 0) {
                                (state.doneBytes.toFloat() / state.totalBytes.toFloat())
                                    .coerceIn(0f, 1f)
                            } else {
                                0f
                            }
                            LinearProgressIndicator(
                                progress = { fraction },
                                modifier = Modifier.fillMaxWidth()
                            )
                            Text("Install: ${state.fileName} (${(fraction * 100).toInt()}%)")
                        }
                        is InstallState.Ready -> Text("Install: ready (${state.dir.name})")
                        is InstallState.Failed -> Text("Install failed: ${state.message}")
                    }
                    when (val state = runtime) {
                        is AppRuntimeState.Idle -> Text("Runtime: idle")
                        is AppRuntimeState.Installing -> Text("Runtime: installing assets")
                        is AppRuntimeState.LoadingModel -> Text("Runtime: loading model")
                        is AppRuntimeState.Ready -> {
                            Text("Runtime: ready")
                            Text("Chunks: ${state.resources.chunkCount}")
                            Text("Model load: ${state.resources.modelLoadTimeMs} ms")
                            Text(
                                "Gate: " +
                                    if (state.resources.gateDatabase != null) "ready" else
                                        "unavailable — ${state.resources.gateInitError ?: "unknown"}"
                            )
                        }
                        is AppRuntimeState.Failed -> Text("Runtime failed: ${state.message}")
                    }
                    if (Diagnostics.exceptionCount() > 0) {
                        Text("Caught exceptions: ${Diagnostics.exceptionCount()}")
                    }
                }
            }

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        "Dense search + refusal gate",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                    OutlinedTextField(
                        value = question,
                        onValueChange = { question = it },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 2,
                        maxLines = 4
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("balanced", "strict").forEach { name ->
                            FilterChip(
                                selected = preset == name,
                                onClick = { preset = name },
                                label = { Text(name) }
                            )
                        }
                    }
                    Button(
                        onClick = {
                            if (!ready || searching) return@Button
                            val loaded = resources ?: return@Button
                            searching = true
                            searchError = null
                            scope.launch {
                                try {
                                    val result = withContext(Dispatchers.Default) {
                                        runDebugSearch(loaded, question, preset)
                                    }
                                    searchState = result
                                } catch (failure: Throwable) {
                                    Diagnostics.recordException(failure)
                                    searchError = failure.message ?: failure.javaClass.simpleName
                                } finally {
                                    searching = false
                                }
                            }
                        },
                        enabled = ready && !searching && question.isNotBlank(),
                        modifier = Modifier.heightIn(min = 48.dp)
                    ) {
                        Text(if (searching) "Searching..." else "Run search")
                    }
                    searchError?.let {
                        Text(it, color = MaterialTheme.colorScheme.error)
                    }
                    searchState?.let { result ->
                        HorizontalDivider()
                        Text(
                            "Preset ${result.preset}: " +
                                if (result.accepted) "ACCEPT" else "REJECT",
                            fontWeight = FontWeight.Bold
                        )
                        Text(
                            "s1=${fmt(result.s1)}  s3=${fmt(result.s3)}  s4=${result.s4}"
                        )
                        Text("stems: ${result.stems.joinToString(" ")}")
                        Text(
                            "Tokenize ${result.timings.tokenizeMs} ms · " +
                                "Embed ${result.timings.embedMs} ms · " +
                                "Search ${result.timings.searchMs} ms · " +
                                "Total ${result.timings.totalMs} ms"
                        )
                        result.hits.forEachIndexed { index, item ->
                            Text(
                                "#${index + 1} chunk ${item.hit.chunkId} | " +
                                    "page ${item.hit.page} | ${fmt(item.hit.score.toDouble())}",
                                style = MaterialTheme.typography.bodySmall,
                                fontWeight = FontWeight.SemiBold
                            )
                            item.chunk?.let { chunk ->
                                Text(
                                    chunk.text.take(180),
                                    style = MaterialTheme.typography.bodySmall
                                )
                            }
                        }
                    }
                }
            }

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        "On-device FTS5 check",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        "Runs SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH '\"heart\"*'.",
                        style = MaterialTheme.typography.bodySmall
                    )
                    Button(
                        onClick = {
                            val database = resources?.gateDatabase ?: return@Button
                            ftsError = null
                            ftsRows = null
                            scope.launch {
                                try {
                                    ftsRows = withContext(Dispatchers.Default) {
                                        database.matchRowCount("\"heart\"*")
                                    }
                                } catch (failure: Throwable) {
                                    Diagnostics.recordException(failure)
                                    ftsError = failure.message ?: failure.javaClass.simpleName
                                }
                            }
                        },
                        enabled = resources?.gateDatabase != null,
                        modifier = Modifier.heightIn(min = 48.dp)
                    ) {
                        Text("Run FTS5 MATCH")
                    }
                    ftsRows?.let { Text("FTS5 rows: $it", fontWeight = FontWeight.Bold) }
                    ftsError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                }
            }

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        "Benchmark",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        "1 warmup + 10 questions × 3 runs.",
                        style = MaterialTheme.typography.bodySmall
                    )
                    Text(
                        "Stages: tokenize · embed · search · gate signals · gate decision · total",
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.SemiBold
                    )
                    Button(
                        onClick = {
                            if (!ready || benchmarking) return@Button
                            val loaded = resources ?: return@Button
                            benchmarking = true
                            benchmark = null
                            benchmarkStatus = "Running warmup..."
                            scope.launch {
                                try {
                                    val result = withContext(Dispatchers.Default) {
                                        val warmupStart = System.nanoTime()
                                        val warmupEmbedding =
                                            loaded.embedder.embedQueryTimed("warmup")
                                        val warmupHits = loaded.denseSearch.search(
                                            warmupEmbedding.vector,
                                            k = 5
                                        )
                                        val warmupMs =
                                            (System.nanoTime() - warmupStart) / 1_000_000
                                        val tokenize = ArrayList<Long>()
                                        val embed = ArrayList<Long>()
                                        val search = ArrayList<Long>()
                                        val gateSignals = ArrayList<Long>()
                                        val gateDecision = ArrayList<Long>()
                                        val total = ArrayList<Long>()
                                        var runs = 0
                                        for (repeat in 1..3) {
                                            for ((index, item) in DEBUG_QUESTIONS.withIndex()) {
                                                val run = (repeat - 1) * DEBUG_QUESTIONS.size +
                                                    index + 1
                                                withContext(Dispatchers.Main) {
                                                    benchmarkStatus =
                                                        "Query $run/30 (round $repeat)"
                                                }
                                                val start = System.nanoTime()
                                                val embedding =
                                                    loaded.embedder.embedQueryTimed(item)
                                                val embedded = System.nanoTime()
                                                val hits = loaded.denseSearch.search(
                                                    embedding.vector,
                                                    k = 5
                                                )
                                                val searched = System.nanoTime()
                                                val top3 = hits.take(3)
                                                val vocab = loaded.gateVocab
                                                val config = loaded.gateConfig
                                                val database = loaded.gateDatabase
                                                if (vocab != null && config != null &&
                                                    database != null
                                                ) {
                                                    val signals = GateSignals.compute(
                                                        question = item,
                                                        top3ChunkIds = top3.map { it.chunkId },
                                                        database = database,
                                                        vocab = vocab
                                                    )
                                                    val gated = System.nanoTime()
                                                    GateDecision.accept(
                                                        hits.firstOrNull()?.score?.toDouble()
                                                            ?: 0.0,
                                                        signals.s3CovTop3,
                                                        signals.s4Unknown,
                                                        config.preset(preset)
                                                    )
                                                    val decided = System.nanoTime()
                                                    gateSignals.add(
                                                        (gated - searched) / 1_000_000
                                                    )
                                                    gateDecision.add(
                                                        (decided - gated) / 1_000_000
                                                    )
                                                    total.add(
                                                        (decided - start) / 1_000_000
                                                    )
                                                } else {
                                                    gateSignals.add(0)
                                                    gateDecision.add(0)
                                                    total.add((searched - start) / 1_000_000)
                                                }
                                                tokenize.add(embedding.tokenizeMs)
                                                embed.add(embedding.inferenceMs)
                                                search.add((searched - embedded) / 1_000_000)
                                                runs++
                                            }
                                        }
                                        DebugBenchmark(
                                            runs = runs,
                                            stages = listOf(
                                                stats("tokenize", tokenize),
                                                stats("embed", embed),
                                                stats("search", search),
                                                stats("gate signals", gateSignals),
                                                stats("gate decision", gateDecision)
                                            ),
                                            total = stats("total", total),
                                            warmupMs = warmupMs
                                        )
                                    }
                                    benchmark = result
                                    writeBenchmarkCsv(context, result)
                                    benchmarkStatus = "Complete (${result.runs} runs)."
                                } catch (failure: Throwable) {
                                    Diagnostics.recordException(failure)
                                    benchmarkStatus =
                                        "Benchmark error: ${failure.message ?: failure.javaClass.simpleName}"
                                } finally {
                                    benchmarking = false
                                }
                            }
                        },
                        enabled = ready && !benchmarking,
                        modifier = Modifier.heightIn(min = 48.dp)
                    ) {
                        Text(if (benchmarking) "Benchmarking..." else "Run benchmark")
                    }
                    benchmarkStatus?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall)
                    }
                    benchmark?.let {
                        Text("Warmup: ${it.warmupMs} ms")
                        Text(
                            "| stage | p50 ms | p95 ms | max ms |",
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = FontWeight.Bold
                        )
                        it.stages.forEach { stage ->
                            Text(
                                "| ${stage.name} | ${stage.p50Ms} | ${stage.p95Ms} | " +
                                    "${stage.maxMs} |",
                                modifier = Modifier.testTag(
                                    "benchmark_stage_${stage.name.replace(' ', '_')}"
                                ),
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                        Text(
                            "| total | ${it.total.p50Ms} | ${it.total.p95Ms} | " +
                                "${it.total.maxMs} |",
                            modifier = Modifier.testTag("benchmark_stage_total"),
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }
        }
    }
}

private fun runDebugSearch(
    resources: LoadedResources,
    question: String,
    presetName: String
): DebugSearchState {
    val start = System.nanoTime()
    resources.tokenizer.encode(OnnxEmbedder.QUERY_PREFIX + question, OnnxEmbedder.MAX_LENGTH)
    val tokenized = System.nanoTime()
    val vector = resources.embedder.embedQuery(question)
    val embedded = System.nanoTime()
    val hits = resources.denseSearch.search(vector, k = 5)
    val searched = System.nanoTime()

    val top3 = hits.take(3)
    val vocab = resources.gateVocab
    val config = resources.gateConfig
    val database = resources.gateDatabase
    var s1 = hits.firstOrNull()?.score?.toDouble() ?: 0.0
    var s3 = 0.0
    var s4 = 0
    var accepted = false
    var stems = emptyList<String>()
    if (vocab != null && config != null && database != null) {
        val signals = GateSignals.compute(
            question = question,
            top3ChunkIds = top3.map { it.chunkId },
            database = database,
            vocab = vocab
        )
        val gatePreset = config.preset(presetName)
        s1 = hits.firstOrNull()?.score?.toDouble() ?: 0.0
        s3 = signals.s3CovTop3
        s4 = signals.s4Unknown
        stems = signals.stems
        accepted = GateDecision.accept(s1, s3, s4, gatePreset)
    }
    val gated = System.nanoTime()
    val chunks = resources.repository.getByIds(top3.map { it.chunkId })
    return DebugSearchState(
        preset = presetName,
        s1 = s1,
        s3 = s3,
        s4 = s4,
        accepted = accepted,
        stems = stems,
        hits = top3.map { DebugHit(it, chunks.firstOrNull { chunk -> chunk.id == it.chunkId }) },
        timings = SearchTiming(
            tokenizeMs = (tokenized - start) / 1_000_000,
            embedMs = (embedded - tokenized) / 1_000_000,
            searchMs = (searched - embedded) / 1_000_000,
            totalMs = (gated - start) / 1_000_000,
            gateSignalsMs = (gated - searched) / 1_000_000
        )
    )
}

private fun stats(name: String, values: List<Long>): StageStats {
    if (values.isEmpty()) return StageStats(name, 0, 0, 0)
    val sorted = values.sorted()
    fun percentile(fraction: Double): Long {
        val index = (sorted.size * fraction).toInt().coerceIn(0, sorted.size - 1)
        return sorted[index]
    }
    return StageStats(
        name = name,
        p50Ms = percentile(0.50),
        p95Ms = percentile(0.95),
        maxMs = sorted.last()
    )
}

private fun writeBenchmarkCsv(context: android.content.Context, benchmark: DebugBenchmark) {
    try {
        val dir = context.getExternalFilesDir("reports") ?: context.filesDir
        dir.mkdirs()
        val rows = ArrayList<String>()
        rows.add("stage,p50_ms,p95_ms,max_ms,runs")
        benchmark.stages.forEach { stage ->
            rows.add(
                "${stage.name},${stage.p50Ms},${stage.p95Ms},${stage.maxMs},${benchmark.runs}"
            )
        }
        rows.add(
            "total,${benchmark.total.p50Ms},${benchmark.total.p95Ms}," +
                "${benchmark.total.maxMs},${benchmark.runs}"
        )
        rows.add("warmup,${benchmark.warmupMs},${benchmark.warmupMs}," +
            "${benchmark.warmupMs},1")
        File(dir, "benchmark.csv").writeText(rows.joinToString("\n") + "\n", Charsets.UTF_8)
    } catch (failure: Throwable) {
        Diagnostics.recordException(failure)
    }
}

private fun fmt(value: Double): String = String.format(Locale.ROOT, "%.6f", value)
