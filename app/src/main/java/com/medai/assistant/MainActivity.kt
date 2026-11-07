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
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
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
import com.medai.assistant.diagnostics.Diagnostics
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.gate.AndroidGateDatabase
import com.medai.assistant.gate.GateConfig
import com.medai.assistant.gate.GateDatabase
import com.medai.assistant.gate.GateDecision
import com.medai.assistant.gate.GateSignals
import com.medai.assistant.gate.GateVocab
import com.medai.assistant.search.DenseSearch
import com.medai.assistant.search.SearchResult
import com.medai.assistant.tokenizer.Tokenizer
import com.medai.assistant.ui.SettingsSheet
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileInputStream
import java.util.Locale

class MainActivity : ComponentActivity() {

    private lateinit var installer: AssetInstaller
    private var repository by mutableStateOf<ChunkRepository?>(null)
    private var chunkCount by mutableIntStateOf(0)

    private var tokenizer by mutableStateOf<Tokenizer?>(null)
    private var embedder by mutableStateOf<OnnxEmbedder?>(null)
    private var denseSearch by mutableStateOf<DenseSearch?>(null)
    private var modelLoadTimeMs by mutableLongStateOf(-1L)

    private var gateVocab by mutableStateOf<GateVocab?>(null)
    private var gateConfig by mutableStateOf<GateConfig?>(null)
    private var gateDatabase by mutableStateOf<GateDatabase?>(null)
    private var gateInitError by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)

        val assetSource = ContextAssetSource(applicationContext)
        installer = AssetInstaller(targetBaseDir = filesDir, assetSource = assetSource)

        lifecycleScope.launch {
            Diagnostics.installStatus = "installing"
            try {
                val installedDir = installer.install()
                Diagnostics.installStatus = "READY (${installedDir.name})"
                withContext(Dispatchers.IO) {
                    val manifestText = assetSource.getManifestText()
                    Diagnostics.assetHashCheck = try {
                        AssetInstaller.verifyInstalledAssets(installedDir, manifestText)
                    } catch (e: Exception) {
                        Diagnostics.recordException(e)
                        "ERROR: ${e.message ?: e.javaClass.simpleName}"
                    }

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

                    // Installed big assets keep the manifest's relative path.
                    val tokBin = File(installedDir, "models/embedder/tokenizer.bin")
                    val tokJson = File(installedDir, "models/embedder/tokenizer.json")
                    val tok = if (tokBin.exists()) {
                        Tokenizer.fromBinaryFile(tokBin)
                    } else if (tokJson.exists()) {
                        FileInputStream(tokJson).use { Tokenizer.fromStream(it) }
                    } else null
                    withContext(Dispatchers.Main) {
                        tokenizer = tok
                    }

                    // Load ONNX Embedder
                    val modelFile = File(installedDir, "models/embedder/model_quantized.onnx")
                    if (modelFile.exists() && tok != null) {
                        val emb = OnnxEmbedder(modelFile, tok)
                        val loadTime = emb.loadTimeMs
                        withContext(Dispatchers.Main) {
                            embedder = emb
                            modelLoadTimeMs = loadTime
                            Diagnostics.modelLoadMs = loadTime
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

                    // Load refusal-gate vocabulary/config (small assets, read directly)
                    try {
                        val vocabJson = assetSource.open("gate_vocab.json").use { input ->
                            input.bufferedReader(Charsets.UTF_8).readText()
                        }
                        val configJson = assetSource.open("gate_config.json").use { input ->
                            input.bufferedReader(Charsets.UTF_8).readText()
                        }
                        val vocab = GateVocab.fromJson(vocabJson)
                        val config = GateConfig.fromJson(configJson)
                        withContext(Dispatchers.Main) {
                            gateVocab = vocab
                            gateConfig = config
                            gateInitError = null
                        }
                        if (dbFile.exists()) {
                            val gateDb = AndroidGateDatabase(dbFile)
                            withContext(Dispatchers.Main) {
                                gateDatabase = gateDb
                            }
                        }
                    } catch (e: Exception) {
                        Diagnostics.recordException(e)
                        withContext(Dispatchers.Main) {
                            gateInitError = e.message ?: e.javaClass.simpleName
                        }
                    }
                }
            } catch (e: Exception) {
                Diagnostics.installStatus = "FAILED: ${e.message ?: e.javaClass.simpleName}"
                Diagnostics.recordException(e)
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
                        modelLoadTimeMs = modelLoadTimeMs,
                        gateVocab = gateVocab,
                        gateConfig = gateConfig,
                        gateDatabase = gateDatabase,
                        gateInitError = gateInitError
                    )
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        embedder?.close()
        denseSearch?.close()
        gateDatabase?.close()
    }
}

data class SearchTiming(
    val tokenizeMs: Long,
    val embedMs: Long,
    val searchMs: Long,
    val totalMs: Long,
    /** -1 when the refusal-gate signals were not part of this request. */
    val gateSignalsMs: Long = -1L
)

data class BenchmarkSummary(
    val warmupTotalMs: Long,
    val runsCount: Int,
    val p50Ms: Long,
    val p95Ms: Long,
    val maxMs: Long
)

data class GateUiResult(
    val preset: String,
    val s1: Double,
    val s3: Double,
    val s4: Int,
    val t1: Double,
    val t3: Double,
    val k: Int,
    val stems: List<String>,
    val unknownStems: List<String>,
    val top3ChunkIds: List<Int>,
    val accepted: Boolean,
    val gateAvailable: Boolean,
    val gateError: String?,
    val top3: List<Pair<SearchResult, Chunk?>>
)

const val GATE_REJECTION_SENTENCE = "هذه المعلومة غير مذكورة في الكتب الطبية المدمجة في التطبيق."

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
    modelLoadTimeMs: Long,
    gateVocab: GateVocab?,
    gateConfig: GateConfig?,
    gateDatabase: GateDatabase?,
    gateInitError: String?
) {
    var queryText by remember { mutableStateOf("What are the symptoms and emergency treatment of acute myocardial infarction?") }
    var searchResults by remember { mutableStateOf<List<Pair<SearchResult, Chunk?>>>(emptyList()) }
    var searchTiming by remember { mutableStateOf<SearchTiming?>(null) }
    var isSearching by remember { mutableStateOf(false) }
    var searchError by remember { mutableStateOf<String?>(null) }

    var isBenchmarking by remember { mutableStateOf(false) }
    var benchmarkSummary by remember { mutableStateOf<BenchmarkSummary?>(null) }
    var benchmarkStatus by remember { mutableStateOf<String?>(null) }

    var gateQuestion by remember {
        mutableStateOf("What causes Asherman's syndrome?")
    }
    var gatePresetName by remember { mutableStateOf("balanced") }
    var gateResult by remember { mutableStateOf<GateUiResult?>(null) }
    var gateRunning by remember { mutableStateOf(false) }
    var gateError by remember { mutableStateOf<String?>(null) }

    var ftsRowCount by remember { mutableStateOf<Int?>(null) }
    var ftsRunning by remember { mutableStateOf(false) }
    var ftsError by remember { mutableStateOf<String?>(null) }

    val coroutineScope = rememberCoroutineScope()
    val appContext = LocalContext.current
    val clipboard = LocalClipboardManager.current
    var showSettings by remember { mutableStateOf(false) }
    val isReady = repository != null && tokenizer != null && embedder != null && denseSearch != null

    if (showSettings) {
        SettingsSheet(
            onDismiss = { showSettings = false },
            onCopyDiagnostics = {
                val report = try {
                    Diagnostics.buildReport(appContext)
                } catch (e: Exception) {
                    Diagnostics.recordException(e)
                    "تعذّر إنشاء تقرير التشخيص: ${e.message ?: e.javaClass.simpleName}"
                }
                clipboard.setText(AnnotatedString(report))
                showSettings = false
            }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("MedAI Debug / K4") },
                actions = {
                    TextButton(onClick = { showSettings = true }) {
                        Text("الإعدادات")
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
                                        // Measure the tokenizer separately for the
                                        // diagnostics report (embedQuery tokenizes again).
                                        tokenizer!!.encode(
                                            OnnxEmbedder.QUERY_PREFIX + queryText,
                                            OnnxEmbedder.MAX_LENGTH
                                        )
                                        val t1 = System.nanoTime()
                                        val emb = embedder!!.embedQuery(queryText)
                                        val t2 = System.nanoTime()
                                        val hits = denseSearch!!.search(emb, k = 3)
                                        val t3 = System.nanoTime()

                                        val withChunks = hits.map { hit ->
                                            val chunk = repository?.getById(hit.chunkId)
                                            Pair(hit, chunk)
                                        }

                                        val tm = SearchTiming(
                                            tokenizeMs = (t1 - t0) / 1_000_000,
                                            embedMs = (t2 - t1) / 1_000_000,
                                            searchMs = (t3 - t2) / 1_000_000,
                                            totalMs = (t3 - t0) / 1_000_000
                                        )
                                        Pair(withChunks, tm)
                                    }
                                    searchResults = resultsWithChunks
                                    searchTiming = timing
                                    Diagnostics.recordTimings(queryText, timing)
                                } catch (e: Exception) {
                                    Diagnostics.recordException(e)
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
                            "#${idx + 1} Chunk ID ${hit.chunkId} | Page ${hit.page} | Score ${String.format(Locale.ROOT, "%.4f", hit.score)}",
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

            // 3. Refusal Gate Card (Stage K4)
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Refusal Gate (K4)", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(
                        "s1 = dense top-1 cosine; s3 = stem coverage in dense top-3; " +
                            "s4 = content stems with corpus document frequency 0. " +
                            "Accept when s1 >= t1, s3 >= t3 and s4 <= k.",
                        style = MaterialTheme.typography.bodySmall
                    )

                    if (gateInitError != null) {
                        Surface(
                            shape = MaterialTheme.shapes.small,
                            color = MaterialTheme.colorScheme.errorContainer,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Column(
                                modifier = Modifier.padding(10.dp),
                                verticalArrangement = Arrangement.spacedBy(2.dp)
                            ) {
                                Text(
                                    "تعذّر تشغيل فلتر الرفض",
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.onErrorContainer
                                )
                                Text(
                                    gateInitError ?: "",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onErrorContainer
                                )
                                Text(
                                    "ما زال البحث الدلالي يعمل ويعرض أقرب 3 مقاطع.",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onErrorContainer
                                )
                            }
                        }
                    }

                    OutlinedTextField(
                        value = gateQuestion,
                        onValueChange = { gateQuestion = it },
                        label = { Text("Gate question") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 2,
                        maxLines = 4
                    )

                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("balanced", "strict").forEach { name ->
                            FilterChip(
                                selected = gatePresetName == name,
                                onClick = { gatePresetName = name },
                                label = { Text(name) }
                            )
                        }
                    }

                    Button(
                        onClick = {
                            if (!isReady || gateRunning) return@Button
                            gateRunning = true
                            gateError = null
                            coroutineScope.launch {
                                try {
                                    val (result, timing) = withContext(Dispatchers.Default) {
                                        val question = gateQuestion
                                        val t0 = System.nanoTime()
                                        tokenizer!!.encode(
                                            OnnxEmbedder.QUERY_PREFIX + question,
                                            OnnxEmbedder.MAX_LENGTH
                                        )
                                        val t1 = System.nanoTime()
                                        val emb = embedder!!.embedQuery(question)
                                        val t2 = System.nanoTime()
                                        val hits = denseSearch!!.search(emb, k = 3)
                                        val t3 = System.nanoTime()
                                        val top3 = hits.map { hit ->
                                            Pair(hit, repository?.getById(hit.chunkId))
                                        }
                                        val s1 = hits.firstOrNull()?.score?.toDouble() ?: 0.0
                                        val selectedPreset = gatePresetName
                                        val vocab = gateVocab
                                        val config = gateConfig
                                        val database = gateDatabase

                                        fun unavailable(errorText: String): GateUiResult =
                                            GateUiResult(
                                                preset = selectedPreset,
                                                s1 = s1,
                                                s3 = 0.0,
                                                s4 = 0,
                                                t1 = 0.0,
                                                t3 = 0.0,
                                                k = 0,
                                                stems = emptyList(),
                                                unknownStems = emptyList(),
                                                top3ChunkIds = hits.map { it.chunkId },
                                                accepted = false,
                                                gateAvailable = false,
                                                gateError = errorText,
                                                top3 = top3
                                            )

                                        val gateStarted = System.nanoTime()
                                        val gateResultForRequest = if (
                                            vocab != null && config != null && database != null
                                        ) {
                                            try {
                                                val signals = GateSignals.compute(
                                                    question,
                                                    hits.map { it.chunkId },
                                                    database,
                                                    vocab
                                                )
                                                val preset = config.preset(selectedPreset)
                                                GateUiResult(
                                                    preset = selectedPreset,
                                                    s1 = s1,
                                                    s3 = signals.s3CovTop3,
                                                    s4 = signals.s4Unknown,
                                                    t1 = preset.t1,
                                                    t3 = preset.t3,
                                                    k = preset.k,
                                                    stems = signals.stems,
                                                    unknownStems = signals.unknownStems,
                                                    top3ChunkIds = signals.top3ChunkIds,
                                                    accepted = GateDecision.accept(
                                                        s1,
                                                        signals.s3CovTop3,
                                                        signals.s4Unknown,
                                                        preset
                                                    ),
                                                    gateAvailable = true,
                                                    gateError = null,
                                                    top3 = top3
                                                )
                                            } catch (e: Exception) {
                                                // A gate failure must never hide the
                                                // retrieval result; record it and
                                                // fall back to the top-3 passages.
                                                Diagnostics.recordException(e)
                                                unavailable(
                                                    e.message ?: e.javaClass.simpleName
                                                )
                                            }
                                        } else {
                                            unavailable(
                                                gateInitError ?: "فلتر الرفض غير مهيأ"
                                            )
                                        }
                                        val gateSignalsMs =
                                            (System.nanoTime() - gateStarted) / 1_000_000
                                        val tm = SearchTiming(
                                            tokenizeMs = (t1 - t0) / 1_000_000,
                                            embedMs = (t2 - t1) / 1_000_000,
                                            searchMs = (t3 - t2) / 1_000_000,
                                            totalMs = (t3 - t0) / 1_000_000,
                                            gateSignalsMs = gateSignalsMs
                                        )
                                        gateResultForRequest to tm
                                    }
                                    gateResult = result
                                    Diagnostics.recordTimings(gateQuestion, timing)
                                } catch (e: Exception) {
                                    Diagnostics.recordException(e)
                                    gateError = e.message ?: "Gate check failed"
                                } finally {
                                    gateRunning = false
                                }
                            }
                        },
                        enabled = isReady && !gateRunning && gateQuestion.isNotBlank()
                    ) {
                        Text(if (gateRunning) "Checking..." else "Run gate check")
                    }

                    if (gateError != null) {
                        Text(gateError!!, color = MaterialTheme.colorScheme.error)
                    }

                    gateResult?.let { r ->
                        Surface(
                            shape = MaterialTheme.shapes.small,
                            color = if (r.gateAvailable) {
                                MaterialTheme.colorScheme.primaryContainer
                            } else {
                                MaterialTheme.colorScheme.errorContainer
                            },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                if (!r.gateAvailable) {
                                    Text(
                                        "تعذّر تشغيل فلتر الرفض",
                                        style = MaterialTheme.typography.titleSmall,
                                        fontWeight = FontWeight.Bold,
                                        color = MaterialTheme.colorScheme.onErrorContainer
                                    )
                                    Text(
                                        r.gateError ?: "",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onErrorContainer
                                    )
                                    Text(
                                        "أقرب 3 نتائج من البحث الدلالي:",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onErrorContainer
                                    )
                                } else {
                                    Text(
                                        "DECISION: ${if (r.accepted) "ACCEPT" else "REJECT"} (preset ${r.preset})",
                                        style = MaterialTheme.typography.titleSmall,
                                        fontWeight = FontWeight.Bold
                                    )
                                    Text(
                                        "s1 = ${String.format(Locale.ROOT, "%.6f", r.s1)}  (t1 = ${String.format(Locale.ROOT, "%.6f", r.t1)})",
                                        style = MaterialTheme.typography.bodySmall
                                    )
                                    Text(
                                        "s3 = ${String.format(Locale.ROOT, "%.6f", r.s3)}  (t3 = ${String.format(Locale.ROOT, "%.6f", r.t3)})",
                                        style = MaterialTheme.typography.bodySmall
                                    )
                                    Text("s4 = ${r.s4}  (k = ${r.k})", style = MaterialTheme.typography.bodySmall)
                                    Text("top-3 chunk ids: ${r.top3ChunkIds.joinToString(", ")}", style = MaterialTheme.typography.bodySmall)
                                    Text("stems (${r.stems.size}): ${r.stems.joinToString(" ")}", style = MaterialTheme.typography.bodySmall)
                                    Text(
                                        "unknown stems (${r.unknownStems.size}): " +
                                            if (r.unknownStems.isEmpty()) "(none)" else r.unknownStems.joinToString(" "),
                                        style = MaterialTheme.typography.bodySmall
                                    )
                                    if (!r.accepted) {
                                        Text(
                                            GATE_REJECTION_SENTENCE,
                                            style = MaterialTheme.typography.bodyMedium,
                                            fontWeight = FontWeight.Bold
                                        )
                                    }
                                }

                                r.top3.forEachIndexed { index, (hit, chunk) ->
                                    HorizontalDivider(modifier = Modifier.padding(vertical = 2.dp))
                                    Text(
                                        "#${index + 1} Chunk ${hit.chunkId} | page ${hit.page} | " +
                                            String.format(Locale.ROOT, "%.4f", hit.score),
                                        style = MaterialTheme.typography.bodySmall,
                                        fontWeight = FontWeight.SemiBold
                                    )
                                    chunk?.let { c ->
                                        Text(
                                            "${c.bookName}${if (c.section.isNotBlank()) " — ${c.section}" else ""}",
                                            style = MaterialTheme.typography.bodySmall
                                        )
                                        Text(
                                            if (c.text.length > 180) c.text.take(180) + "..." else c.text,
                                            style = MaterialTheme.typography.bodySmall
                                        )
                                    }
                                }
                            }
                        }
                    }

                    HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
                    Text(
                        "On-device FTS5 check (labelled test)",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        "Runs one real SQLite FTS5 query against chunks_fts on this device: " +
                            "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH '\"heart\"*'. " +
                            "The JVM tests cannot prove the Android SQLite build supports FTS5.",
                        style = MaterialTheme.typography.bodySmall
                    )
                    Button(
                        onClick = {
                            if (gateDatabase == null || ftsRunning) return@Button
                            ftsRunning = true
                            ftsError = null
                            ftsRowCount = null
                            coroutineScope.launch {
                                try {
                                    val count = withContext(Dispatchers.Default) {
                                        gateDatabase!!.matchRowCount("\"heart\"*")
                                    }
                                    ftsRowCount = count
                                } catch (e: Exception) {
                                    Diagnostics.recordException(e)
                                    ftsError = e.message ?: "FTS5 check failed"
                                } finally {
                                    ftsRunning = false
                                }
                            }
                        },
                        enabled = gateDatabase != null && !ftsRunning
                    ) {
                        Text(if (ftsRunning) "Running FTS5 MATCH..." else "Run on-device FTS5 MATCH check")
                    }
                    ftsRowCount?.let {
                        Text(
                            "FTS5 MATCH rows for \"heart\"*: $it",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold
                        )
                    }
                    if (ftsError != null) {
                        Text("FTS5 error: $ftsError", color = MaterialTheme.colorScheme.error)
                    }
                }
            }

            // 4. On-Device Benchmark Card
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
                                    Diagnostics.recordException(e)
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
