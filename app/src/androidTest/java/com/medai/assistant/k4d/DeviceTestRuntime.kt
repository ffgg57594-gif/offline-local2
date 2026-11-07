package com.medai.assistant.k4d

import android.content.Context
import androidx.test.platform.app.InstrumentationRegistry
import com.medai.assistant.data.AndroidChunkRepository
import com.medai.assistant.data.AssetInstaller
import com.medai.assistant.data.ChunkRepository
import com.medai.assistant.data.ContextAssetSource
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.gate.AndroidGateDatabase
import com.medai.assistant.gate.GateConfig
import com.medai.assistant.gate.GateDatabase
import com.medai.assistant.gate.GateReference
import com.medai.assistant.gate.GateReferenceRow
import com.medai.assistant.gate.GateVocab
import com.medai.assistant.search.DenseSearch
import com.medai.assistant.tokenizer.Tokenizer
import kotlinx.coroutines.runBlocking
import java.io.File
import java.io.InputStream

/**
 * One installed asset directory + one model + one DB per instrumented test
 * process. Loading the 118 MB model once keeps the emulator suite fast.
 */
object DeviceTestRuntime {
    private val targetContext: Context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    private val testContext: Context
        get() = InstrumentationRegistry.getInstrumentation().context

    val installedDir: File by lazy {
        runBlocking {
            AssetInstaller(
                targetBaseDir = targetContext.filesDir,
                assetSource = ContextAssetSource(targetContext)
            ).install()
        }
    }

    fun installedFile(path: String): File = File(installedDir, path)

    val tokenizer: Tokenizer by lazy {
        Tokenizer.fromBinaryFile(installedFile("models/embedder/tokenizer.bin"))
    }

    val embedder: OnnxEmbedder by lazy {
        OnnxEmbedder(installedFile("models/embedder/model_quantized.onnx"), tokenizer)
    }

    val repository: ChunkRepository by lazy {
        AndroidChunkRepository(installedFile("books_knowledge.db"))
    }

    val denseSearch: DenseSearch by lazy {
        DenseSearch(
            installedFile("embeddings.bin"),
            1185,
            384,
            repository.getAllPages(1185)
        )
    }

    val gateDatabase: GateDatabase by lazy {
        AndroidGateDatabase(installedFile("books_knowledge.db"))
    }

    val vocab: GateVocab by lazy { GateVocab.fromJson(mainAssetText("gate_vocab.json")) }

    val config: GateConfig by lazy { GateConfig.fromJson(mainAssetText("gate_config.json")) }

    val reference: List<GateReferenceRow> by lazy {
        GateReference.fromJson(mainAssetText("gate_reference.json"))
    }

    fun mainAssetText(path: String): String {
        return targetContext.assets.open(path).use { input ->
            input.bufferedReader(Charsets.UTF_8).readText()
        }
    }

    fun testAssetText(path: String): String {
        return testContext.assets.open(path).use { input ->
            input.bufferedReader(Charsets.UTF_8).readText()
        }
    }

    fun testAsset(path: String): InputStream = testContext.assets.open(path)
}
