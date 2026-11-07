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

private data class DebugBenchmark(
    val runs: Int,
    val p50Ms: Long,
    val p95Ms: Long,
    val maxMs: Long,
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
                                        val warmupVector = loaded.embedder.embedQuery("warmup")
                                        loaded.denseSearch.search(warmupVector, k = 5)
                                        val warmupMs =
                                            (System.nanoTime() - warmupStart) / 1_000_000
                                        val latencies = ArrayList<Long>()
                                        for (repeat in 1..3) {
                                            for ((index, item) in DEBUG_QUESTIONS.withIndex()) {
                                                val run = (repeat - 1) * DEBUG_QUESTIONS.size +
                                                    index + 1
                                                withContext(Dispatchers.Main) {
                                                    benchmarkStatus =
                                                        "Query $run/30 (round $repeat)"
                                                }
                                                val start = System.nanoTime()
                                                val vector = loaded.embedder.embedQuery(item)
                                                loaded.denseSearch.search(vector, k = 5)
                                                latencies.add(
                                                    (System.nanoTime() - start) / 1_000_000
                                                )
                                            }
                                        }
                                        latencies.sort()
                                        DebugBenchmark(
                                            runs = latencies.size,
                                            p50Ms = latencies[
                                                (latencies.size * 0.50).toInt()
                                                    .coerceAtMost(latencies.size - 1)
                                            ],
                                            p95Ms = latencies[
                                                (latencies.size * 0.95).toInt()
                                                    .coerceAtMost(latencies.size - 1)
                                            ],
                                            maxMs = latencies.maxOrNull() ?: 0L,
                                            warmupMs = warmupMs
                                        )
                                    }
                                    benchmark = result
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
                        Text("p50: ${it.p50Ms} ms")
                        Text("p95: ${it.p95Ms} ms")
                        Text("max: ${it.maxMs} ms")
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

private fun fmt(value: Double): String = String.format(Locale.ROOT, "%.6f", value)
