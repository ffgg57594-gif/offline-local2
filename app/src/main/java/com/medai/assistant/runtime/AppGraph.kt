package com.medai.assistant.runtime

import android.content.Context
import android.os.Process
import android.os.SystemClock
import com.medai.assistant.data.AndroidChunkRepository
import com.medai.assistant.data.AssetInstaller
import com.medai.assistant.data.ChunkRepository
import com.medai.assistant.data.ContextAssetSource
import com.medai.assistant.data.InstallState
import com.medai.assistant.diagnostics.Diagnostics
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.gate.AndroidGateDatabase
import com.medai.assistant.gate.GateConfig
import com.medai.assistant.gate.GateDatabase
import com.medai.assistant.gate.GateVocab
import com.medai.assistant.search.DenseSearch
import com.medai.assistant.tokenizer.Tokenizer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileInputStream

data class LoadedResources(
    val installDir: File,
    val repository: ChunkRepository,
    val chunkCount: Int,
    val tokenizer: Tokenizer,
    val embedder: OnnxEmbedder,
    val denseSearch: DenseSearch,
    val gateVocab: GateVocab?,
    val gateConfig: GateConfig?,
    val gateDatabase: GateDatabase?,
    val gateInitError: String?,
    val modelLoadTimeMs: Long
)

sealed interface AppRuntimeState {
    data object Idle : AppRuntimeState
    data object Installing : AppRuntimeState
    data object LoadingModel : AppRuntimeState
    data class Ready(val resources: LoadedResources) : AppRuntimeState
    data class Failed(val message: String) : AppRuntimeState
}

/**
 * Process-wide owner of the installer and the heavy model/tokenizer/matrix
 * objects. Compose may recreate the Activity on rotation; this object does not
 * reload ONNX or re-copy assets.
 */
object AppGraph {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _runtimeState = MutableStateFlow<AppRuntimeState>(AppRuntimeState.Idle)
    val runtimeState: StateFlow<AppRuntimeState> = _runtimeState.asStateFlow()

    private val _installState = MutableStateFlow<InstallState>(InstallState.Idle)
    val installState: StateFlow<InstallState> = _installState.asStateFlow()

    @Volatile
    private var loadedResources: LoadedResources? = null

    @Volatile
    private var started = false

    @Synchronized
    fun start(context: Context) {
        if (started) return
        started = true
        val app = context.applicationContext
        scope.launch {
            try {
                _runtimeState.value = AppRuntimeState.Installing
                val assetSource = ContextAssetSource(app)
                val installer = AssetInstaller(
                    targetBaseDir = app.filesDir,
                    assetSource = assetSource
                )
                val installCollector = scope.launch {
                    installer.installState.collect { _installState.value = it }
                }
                Diagnostics.installStatus = "installing"
                val installedDir = installer.install()
                installCollector.cancel()
                Diagnostics.installStatus = "READY (${installedDir.name})"
                _installState.value = InstallState.Ready(installedDir)

                _runtimeState.value = AppRuntimeState.LoadingModel
                val loaded = loadResources(app, installedDir, assetSource)
                loadedResources = loaded
                Diagnostics.coldStartMs =
                    SystemClock.uptimeMillis() - Process.getStartUptimeMillis()
                _runtimeState.value = AppRuntimeState.Ready(loaded)
            } catch (failure: Throwable) {
                Diagnostics.recordException(failure)
                Diagnostics.installStatus =
                    "FAILED: ${failure.message ?: failure.javaClass.simpleName}"
                _runtimeState.value = AppRuntimeState.Failed(
                    failure.message ?: failure.javaClass.simpleName
                )
            }
        }
    }

    fun requireResources(): LoadedResources {
        return loadedResources
            ?: error("The model is not ready yet")
    }

    fun currentResources(): LoadedResources? = loadedResources

    private fun loadResources(
        app: Context,
        installedDir: File,
        assetSource: ContextAssetSource
    ): LoadedResources {
        val manifestText = assetSource.getManifestText()
        Diagnostics.assetHashCheck = try {
            AssetInstaller.verifyInstalledAssets(installedDir, manifestText)
        } catch (failure: Throwable) {
            Diagnostics.recordException(failure)
            "ERROR: ${failure.message ?: failure.javaClass.simpleName}"
        }

        val dbFile = File(installedDir, "books_knowledge.db")
        require(dbFile.exists()) { "books_knowledge.db is missing after installation" }
        val repository = AndroidChunkRepository(dbFile)
        val chunkCount = repository.count()
        require(chunkCount > 0) { "books_knowledge.db contains no chunks" }
        val pagesArray = repository.getAllPages(1185)

        val tokBin = File(installedDir, "models/embedder/tokenizer.bin")
        val tokJson = File(installedDir, "models/embedder/tokenizer.json")
        val tokenizer = when {
            tokBin.exists() -> Tokenizer.fromBinaryFile(tokBin)
            tokJson.exists() -> FileInputStream(tokJson).use { Tokenizer.fromStream(it) }
            else -> error("tokenizer.bin/tokenizer.json is missing")
        }

        val modelFile = File(installedDir, "models/embedder/model_quantized.onnx")
        require(modelFile.exists()) { "model_quantized.onnx is missing" }
        val embedder = OnnxEmbedder(modelFile, tokenizer)
        Diagnostics.modelLoadMs = embedder.loadTimeMs
        Diagnostics.modelLoadCount += 1

        val embeddingsFile = File(installedDir, "embeddings.bin")
        require(embeddingsFile.exists()) { "embeddings.bin is missing" }
        val denseSearch = DenseSearch(embeddingsFile, 1185, 384, pagesArray)

        var gateVocab: GateVocab? = null
        var gateConfig: GateConfig? = null
        var gateDatabase: GateDatabase? = null
        var gateInitError: String? = null
        try {
            gateVocab = GateVocab.fromJson(
                assetSource.open("gate_vocab.json").use {
                    it.bufferedReader(Charsets.UTF_8).readText()
                }
            )
            gateConfig = GateConfig.fromJson(
                assetSource.open("gate_config.json").use {
                    it.bufferedReader(Charsets.UTF_8).readText()
                }
            )
            gateDatabase = AndroidGateDatabase(dbFile)
        } catch (failure: Throwable) {
            // The refusal gate is optional: native SQLite failures must not
            // prevent the dense search screen from working.
            Diagnostics.recordException(failure)
            gateInitError = failure.message ?: failure.javaClass.simpleName
            gateVocab = null
            gateConfig = null
            gateDatabase = null
        }

        return LoadedResources(
            installDir = installedDir,
            repository = repository,
            chunkCount = chunkCount,
            tokenizer = tokenizer,
            embedder = embedder,
            denseSearch = denseSearch,
            gateVocab = gateVocab,
            gateConfig = gateConfig,
            gateDatabase = gateDatabase,
            gateInitError = gateInitError,
            modelLoadTimeMs = embedder.loadTimeMs
        )
    }
}
