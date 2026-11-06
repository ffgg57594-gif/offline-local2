package com.medai.assistant

import android.content.res.Configuration
import android.os.Bundle
import android.os.Debug
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.lifecycle.lifecycleScope
import com.medai.assistant.data.AndroidChunkRepository
import com.medai.assistant.data.AssetInstaller
import com.medai.assistant.data.Chunk
import com.medai.assistant.data.ChunkRepository
import com.medai.assistant.data.ContextAssetSource
import com.medai.assistant.data.InstallState
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.search.DenseSearch
import com.medai.assistant.search.SearchResult
import com.medai.assistant.tokenizer.Tokenizer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileInputStream

class MainActivity : ComponentActivity() {

    private lateinit var installer: AssetInstaller
    private var repository by mutableStateOf<ChunkRepository?>(null)
    private var chunkCount by mutableIntStateOf(0)

    private var tokenizer by mutableStateOf<Tokenizer?>(null)
    private var embedder by mutableStateOf<OnnxEmbedder?>(null)
    private var denseSearch by mutableStateOf<DenseSearch?>(null)
    private var modelLoadTimeMs by mutableLongStateOf(-1L)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)

        val assetSource = ContextAssetSource(applicationContext)
        installer = AssetInstaller(targetBaseDir = filesDir, assetSource = assetSource)

        lifecycleScope.launch {
            try {
                val installedDir = installer.install()
                withContext(Dispatchers.IO) {
                    val dbFile = File(installedDir, "books_knowledge.db")
                    var repo: ChunkRepository? = null
                    var pagesArray = IntArray(1185)
                    if (dbFile.exists()) {
                        val r = AndroidChunkRepository(dbFile)
                        val count = r.count()
                        pagesArray = r.getAllPages(count)
                        repo = r
                        withContext(Dispatchers.Main) {
                            chunkCount = count
                            repository = repo
                        }
                    }

                    // Load tokenizer
                    val tokBin = File(installedDir, "tokenizer.bin")
                    val tokJson = File(installedDir, "tokenizer.json")
                    val tok = if (tokBin.exists()) {
                        Tokenizer.fromBinaryFile(tokBin)
                    } else if (tokJson.exists()) {
                        FileInputStream(tokJson).use { Tokenizer.fromStream(it) }
                    } else null
                    withContext(Dispatchers.Main) {
                        tokenizer = tok
                    }

                    // Load ONNX Embedder
                    val modelFile = File(installedDir, "model_quantized.onnx")
                    if (modelFile.exists() && tok != null) {
                        val emb = OnnxEmbedder(modelFile, tok)
                        val loadTime = emb.loadTimeMs
                        withContext(Dispatchers.Main) {
                            embedder = emb
                            modelLoadTimeMs = loadTime
                        }
                    }

                    // Load DenseSearch
                    val embBin = File(installedDir, "embeddings.bin")
                    if (embBin.exists()) {
                        val ds = DenseSearch(embBin, 1185, 384, pagesArray)
                        withContext(Dispatchers.Main) {
                            denseSearch = ds
                        }
                    }
                }
            } catch (e: Exception) {
                // InstallState.Failed is already set by installer
            }
        }

        setContent {
            val isDark = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) ==
                    Configuration.UI_MODE_NIGHT_YES
            val colorScheme = if (isDark) darkColorScheme() else lightColorScheme()

            MaterialTheme(colorScheme = colorScheme) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    val installState by installer.installState.collectAsState()
                    DebugScreen(
                        installState = installState,
                        chunkCount = chunkCount,
                        repository = repository,
                        tokenizer = tokenizer,
                        embedder = embedder,
                        denseSearch = denseSearch,
                        modelLoadTimeMs = modelLoadTimeMs
                    )
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        embedder?.close()
        denseSearch?.close()
    }
}

data class SearchTiming(
    val tokenizeMs: Long,
    val embedMs: Long,
    val searchMs: Long,
    val totalMs: Long
)

data class BenchmarkSummary(
    val warmupTotalMs: Long,
    val runsCount: Int,
    val p50Ms: Long,
    val p95Ms: Long,
    val maxMs: Long
)

val SAMPLE_QUESTIONS = listOf(
    "What is the first-line treatment for uncomplicated community-acquired pneumonia?",
    "How is acute appendicitis diagnosed in adults?",
    "What are the diagnostic criteria for type 2 diabetes mellitus?",
    "What is the recommended initial management for ST-elevation myocardial infarction?",
    "How does bacterial meningitis present clinically in children?",
    "What are the major complications of chronic kidney disease stage 4?",
    "What is the management of status epilepticus in the emergency department?",
    "How is pulmonary embolism diagnosed using clinical scores and imaging?",
    "What are the treatment options for primary hypertension?",
    "What are the signs and initial treatment of anaphylaxis?"
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebugScreen(
    installState: InstallState,
    chunkCount: Int,
    repository: ChunkRepository?,
    tokenizer: Tokenizer?,
    embedder: OnnxEmbedder?,
    denseSearch: DenseSearch?,
    modelLoadTimeMs: Long
) {
    var queryText by remember { mutableStateOf("What are the symptoms and emergency treatment of acute myocardial infarction?") }
    var searchResults by remember { mutableStateOf<List<Pair<SearchResult, Chunk?>>>(emptyList()) }
    var searchTiming by remember { mutableStateOf<SearchTiming?>(null) }
    var isSearching by remember { mutableStateOf(false) }
    var searchError by remember { mutableStateOf<String?>(null) }

    var isBenchmarking by remember { mutableStateOf(false) }
    var benchmarkSummary by remember { mutableStateOf<BenchmarkSummary?>(null) }
    var benchmarkStatus by remember { mutableStateOf<String?>(null) }

    val coroutineScope = rememberCoroutineScope()
    val isReady = repository != null && tokenizer != null && embedder != null && denseSearch != null

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("MedAI Debug / K3") },
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
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // 1. Device & Runtime Telemetry Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Device & Embedder Telemetry", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    val cores = Runtime.getRuntime().availableProcessors()
                    Text("CPU Cores: $cores")
                    Text("ONNX Runtime Version: 1.18.0")
                    if (modelLoadTimeMs >= 0) {
                        Text("Model Load Time: $modelLoadTimeMs ms")
                    } else {
                        Text("Model: Loading...")
                    }

                    val memInfo = Debug.MemoryInfo()
                    Debug.getMemoryInfo(memInfo)
                    val totalPssKb = memInfo.totalPss
                    Text("Current Process PSS: ${totalPssKb / 1024} MB ($totalPssKb KB)")

                    when (val state = installState) {
                        is InstallState.Copying -> {
                            val progress = if (state.totalBytes > 0) state.doneBytes.toFloat() / state.totalBytes.toFloat() else 0f
                            LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
                            Text("Installing assets: ${state.fileName} (${(progress * 100).toInt()}%)", style = MaterialTheme.typography.bodySmall)
                        }
                        is InstallState.Failed -> {
                            Text("Install Error: ${state.message}", color = MaterialTheme.colorScheme.error)
                        }
                        is InstallState.Ready -> {
                            Text("Assets: Verified & Ready (${chunkCount} chunks)", color = MaterialTheme.colorScheme.primary)
                        }
                        else -> {}
                    }
                }
            }

            // 2. Interactive Search Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Dense Vector Search", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)

                    OutlinedTextField(
                        value = queryText,
                        onValueChange = { queryText = it },
                        label = { Text("Medical Query") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 2,
                        maxLines = 4
                    )

                    Button(
                        onClick = {
                            if (!isReady || isSearching) return@Button
                            isSearching = true
                            searchError = null
                            coroutineScope.launch {
                                try {
                                    val (resultsWithChunks, timing) = withContext(Dispatchers.Default) {
                                        val t0 = System.nanoTime()
                                        // embedQuery already prepends "query: " internally
                                        val emb = embedder!!.embedQuery(queryText)
                                        val t1 = System.nanoTime()
                                        val hits = denseSearch!!.search(emb, k = 3)
                                        val t2 = System.nanoTime()

                                        val withChunks = hits.map { hit ->
                                            val chunk = repository?.getById(hit.chunkId)
                                            Pair(hit, chunk)
                                        }

                                        val tm = SearchTiming(
                                            tokenizeMs = 0L,
                                            embedMs = (t1 - t0) / 1_000_000,
                                            searchMs = (t2 - t1) / 1_000_000,
                                            totalMs = (t2 - t0) / 1_000_000
                                        )
                                        Pair(withChunks, tm)
                                    }
                                    searchResults = resultsWithChunks
                                    searchTiming = timing
                                } catch (e: Exception) {
                                    searchError = e.message ?: "Search failed"
                                } finally {
                                    isSearching = false
                                }
                            }
                        },
                        enabled = isReady && !isSearching && queryText.isNotBlank(),
                        modifier = Modifier.align(Alignment.End)
                    ) {
                        Text(if (isSearching) "Searching..." else "Search")
                    }

                    if (searchError != null) {
                        Text(searchError!!, color = MaterialTheme.colorScheme.error)
                    }

                    searchTiming?.let { tm ->
                        Surface(
                            shape = MaterialTheme.shapes.small,
                            color = MaterialTheme.colorScheme.primaryContainer,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Column(modifier = Modifier.padding(8.dp)) {
                                Text(
                                    "Latencies: Embed=${tm.embedMs}ms | Search=${tm.searchMs}ms | Total=${tm.totalMs}ms",
                                    style = MaterialTheme.typography.bodySmall,
                                    fontWeight = FontWeight.SemiBold,
                                    color = MaterialTheme.colorScheme.onPrimaryContainer
                                )
                            }
                        }
                    }

                    searchResults.forEachIndexed { idx, (hit, chunk) ->
                        HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
                        Text(
                            "#${idx + 1} Chunk ID ${hit.chunkId} | Page ${hit.page} | Score ${String.format("%.4f", hit.score)}",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold
                        )
                        chunk?.let { c ->
                            Text("Book: ${c.bookName} ${if (c.section.isNotBlank()) "— " + c.section else ""}", style = MaterialTheme.typography.bodySmall)
                            val snippet = if (c.text.length > 200) c.text.take(200) + "..." else c.text
                            Text(snippet, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 2.dp))
                        }
                    }
                }
            }

            // 3. On-Device Benchmark Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("On-Device Benchmark", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(
                        "Runs 1 warmup pass + 10 medical questions x 3 iterations (30 measured runs) to evaluate on-device p50 / p95 / max latency.",
                        style = MaterialTheme.typography.bodySmall
                    )

                    Button(
                        onClick = {
                            if (!isReady || isBenchmarking) return@Button
                            isBenchmarking = true
                            benchmarkStatus = "Running warmup pass..."
                            benchmarkSummary = null

                            coroutineScope.launch {
                                try {
                                    val summary = withContext(Dispatchers.Default) {
                                        // Warmup pass
                                        val w0 = System.nanoTime()
                                        val wEmb = embedder!!.embedQuery("warmup question")
                                        denseSearch!!.search(wEmb, k = 5)
                                        val warmupTotalMs = (System.nanoTime() - w0) / 1_000_000

                                        val latencies = mutableListOf<Long>()
                                        for (rep in 1..3) {
                                            for ((qIdx, q) in SAMPLE_QUESTIONS.withIndex()) {
                                                val runIdx = (rep - 1) * SAMPLE_QUESTIONS.size + qIdx + 1
                                                withContext(Dispatchers.Main) {
                                                    benchmarkStatus = "Running query $runIdx/30 (Rep $rep)..."
                                                }
                                                val start = System.nanoTime()
                                                val emb = embedder!!.embedQuery(q)
                                                denseSearch!!.search(emb, k = 5)
                                                val durationMs = (System.nanoTime() - start) / 1_000_000
                                                latencies.add(durationMs)
                                            }
                                        }

                                        latencies.sort()
                                        val p50 = latencies[(latencies.size * 0.50).toInt().coerceAtMost(latencies.size - 1)]
                                        val p95 = latencies[(latencies.size * 0.95).toInt().coerceAtMost(latencies.size - 1)]
                                        val max = latencies.maxOrNull() ?: 0L

                                        BenchmarkSummary(
                                            warmupTotalMs = warmupTotalMs,
                                            runsCount = latencies.size,
                                            p50Ms = p50,
                                            p95Ms = p95,
                                            maxMs = max
                                        )
                                    }
                                    benchmarkSummary = summary
                                    benchmarkStatus = "Benchmark complete (${summary.runsCount} runs)."
                                } catch (e: Exception) {
                                    benchmarkStatus = "Benchmark error: ${e.message}"
                                } finally {
                                    isBenchmarking = false
                                }
                            }
                        },
                        enabled = isReady && !isBenchmarking
                    ) {
                        Text(if (isBenchmarking) "Benchmarking..." else "Run Benchmark (30 runs)")
                    }

                    benchmarkStatus?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall)
                    }

                    benchmarkSummary?.let { sum ->
                        Surface(
                            shape = MaterialTheme.shapes.small,
                            color = MaterialTheme.colorScheme.secondaryContainer,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text("Warmup Run (Excluded): ${sum.warmupTotalMs} ms", style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold)
                                Text("Measured Runs: ${sum.runsCount} queries", style = MaterialTheme.typography.bodySmall)
                                Text("Latency p50: ${sum.p50Ms} ms", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
                                Text("Latency p95: ${sum.p95Ms} ms", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
                                Text("Latency Max: ${sum.maxMs} ms", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                }
            }
        }
    }
}
