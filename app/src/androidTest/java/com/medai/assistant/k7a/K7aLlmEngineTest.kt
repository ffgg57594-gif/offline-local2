package com.medai.assistant.k7a

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.medai.assistant.k5b.K5bArtifacts
import com.medai.assistant.llm.LlamaEngine
import com.medai.assistant.llm.Sha256Util
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * K7a: on-device engine tests.
 *
 * The tiny public GGUF (ggml-org/test-model-stories260K, GGUF v3
 * re-export of karpathy/tinyllamas, MIT) is downloaded through the
 * production ModelManager + DownloadManager path and its pinned sha256
 * is re-verified in the test. Then: greedy determinism (20 tokens
 * twice must match byte for byte), mid-generation cancel, free/reload,
 * a corrupted file must be rejected without crashing, and 10
 * load/generate/free cycles must not grow the native heap.
 */
@RunWith(AndroidJUnit4::class)
class K7aLlmEngineTest {

    companion object {
        @Volatile
        private var modelFile: File? = null

        @BeforeClass
        @JvmStatic
        fun downloadOnce() {
            val context = InstrumentationRegistry.getInstrumentation().targetContext
            modelFile = K7aTestModels.ensureDownloaded(context)
        }
    }

    private val context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun modelFile(): File =
        modelFile ?: K7aTestModels.ensureDownloaded(context)

    @Test
    fun downloadedFileMatchesPinnedSha256() {
        val file = modelFile()
        assertEquals(K7aTestModels.TINY_SIZE_BYTES, file.length())
        assertEquals(K7aTestModels.TINY_SHA256, Sha256Util.digestFile(file))
    }

    @Test
    fun greedyGenerationIsDeterministic(): Unit = runBlocking {
        val engine = LlamaEngine.load(
            path = modelFile().absolutePath,
            nCtx = 256,
            nBatch = 256,
            nThreads = 4
        )
        try {
            val first = runEngine(engine, "Once upon a time", 20)
            val second = runEngine(engine, "Once upon a time", 20)
            assertEquals(
                "greedy decoding with a fixed sampler must reproduce identical output",
                first,
                second
            )
            assertTrue("generation must produce at least some text", first.isNotBlank())
            assertTrue(
                "model info should report the clamped context",
                engine.modelInfo.nCtx in 1..256
            )
            assertTrue(
                "tiny test model has no chat template",
                !engine.modelInfo.hasChatTemplate
            )
        } finally {
            engine.free()
        }
    }

    @Test
    fun cancelStopsGenerationAfterFirstToken(): Unit = runBlocking {
        val engine = LlamaEngine.load(
            path = modelFile().absolutePath,
            nCtx = 256,
            nBatch = 256,
            nThreads = 4
        )
        try {
            val tokens = StringBuilder()
            val result = engine.generate(
                prompt = "Once upon a time there was a little dragon who",
                maxTokens = 500,
                onToken = { piece ->
                    tokens.append(piece)
                    engine.cancel()
                }
            )
            assertFalse("a cancelled run must report completed=false", result.completed)
            assertTrue(
                "cancel must kick in after the first token, well before 500",
                result.stats.outputTokens < 500
            )
            assertTrue("some tokens should still stream before cancel", tokens.isNotEmpty())
        } finally {
            engine.free()
        }
    }

    @Test
    fun freeThenReloadWorks(): Unit = runBlocking {
        val first = LlamaEngine.load(
            path = modelFile().absolutePath,
            nCtx = 256,
            nBatch = 256,
            nThreads = 4
        )
        val outputA = runEngine(first, "The king said", 10)
        first.free()
        first.free() // double free must be a no-op, not a crash

        val second = LlamaEngine.load(
            path = modelFile().absolutePath,
            nCtx = 256,
            nBatch = 256,
            nThreads = 4
        )
        try {
            val outputB = runEngine(second, "The king said", 10)
            assertEquals("reload must reproduce the same greedy output", outputA, outputB)
        } finally {
            second.free()
        }
    }

    @Test
    fun corruptedModelIsRejectedGracefully(): Unit = runBlocking {
        val corrupted = File(context.cacheDir, "k7a-corrupted.gguf")
        modelFile().copyTo(corrupted, overwrite = true)
        // Flip one byte in the header (the version field at offset 4) while
        // keeping the rest of the file; the load must fail, not crash.
        java.io.RandomAccessFile(corrupted, "rw").use { raf ->
            raf.seek(4L)
            val current = raf.read()
            raf.seek(4L)
            raf.write(current xor 0xFF)
        }
        var message: String? = null
        try {
            LlamaEngine.load(corrupted.absolutePath, nCtx = 256, nBatch = 256, nThreads = 4)
        } catch (expected: IllegalStateException) {
            message = expected.message
        }
        assertTrue(
            "load must fail with a clear message, got: $message",
            message != null && message.contains("فشل تحميل الموديل")
        )
        corrupted.delete()
    }

    @Test
    fun tenLoadGenerateFreeCyclesDoNotLeakNativeMemory(): Unit = runBlocking {
        val infoBefore = android.os.Debug.MemoryInfo()
        android.os.Debug.getMemoryInfo(infoBefore)
        val nativeBefore = infoBefore.nativePss

        val stats = StringBuilder()
        var maxTotalPss = 0L
        repeat(10) { cycle ->
            val engine = LlamaEngine.load(
                path = modelFile().absolutePath,
                nCtx = 256,
                nBatch = 256,
                nThreads = 4
            )
            try {
                val started = System.nanoTime()
                val result = engine.generate(
                    prompt = "Once upon a time",
                    maxTokens = 20
                ) { }
                val elapsedMs = (System.nanoTime() - started) / 1_000_000
                stats.appendLine(
                    "cycle=$cycle loadMs=${engine.loadMs} genMs=$elapsedMs " +
                        "promptTokens=${result.stats.promptTokens} " +
                        "outputTokens=${result.stats.outputTokens} " +
                        "ttftMs=${result.stats.timeToFirstTokenMs} " +
                        "tokPerSec=${String.format(java.util.Locale.US, "%.2f", result.stats.tokensPerSecond)}"
                )
                val info = android.os.Debug.MemoryInfo()
                android.os.Debug.getMemoryInfo(info)
                maxTotalPss = maxOf(maxTotalPss, info.totalPss.toLong())
            } finally {
                engine.free()
            }
        }

        val infoAfter = android.os.Debug.MemoryInfo()
        android.os.Debug.getMemoryInfo(infoAfter)
        val nativeAfter = infoAfter.nativePss
        val growthKb = nativeAfter - nativeBefore
        stats.appendLine("nativePssBeforeKb=$nativeBefore nativePssAfterKb=$nativeAfter")
        stats.appendLine("peakTotalPssKb=$maxTotalPss")
        K5bArtifacts.writeK7aText(context, "k7a_engine_native_heap.txt", stats.toString())
        assertTrue(
            "native heap must not grow beyond 64 MB after 10 cycles (grew $growthKb kb)",
            growthKb < 65_536
        )
    }

    @Test
    fun writesEngineStatsReportForTheReport(): Unit = runBlocking {
        val engine = LlamaEngine.load(
            path = modelFile().absolutePath,
            nCtx = 256,
            nBatch = 256,
            nThreads = 4
        )
        try {
            val short = engine.generate(prompt = "Once upon a time", maxTokens = 20) { }
            val medium = engine.generate(
                prompt = "A long time ago in a distant kingdom there lived a " +
                    "princess who loved to walk through the forest and listen " +
                    "to the birds sing every morning.",
                maxTokens = 20
            ) { }
            val report = buildString {
                appendLine("K7a emulator engine stats (stories260K-f32)")
                appendLine("loadMs=${engine.loadMs}")
                appendLine("desc=${engine.modelInfo.desc}")
                appendLine("nCtx=${engine.modelInfo.nCtx} nCtxTrain=${engine.modelInfo.nCtxTrain}")
                appendLine("nVocab=${engine.modelInfo.nVocab} sizeBytes=${engine.modelInfo.sizeBytes}")
                appendLine("hasChatTemplate=${engine.modelInfo.hasChatTemplate}")
                appendLine("short: ttftMs=${short.stats.timeToFirstTokenMs} " +
                    "tokPerSec=${String.format(java.util.Locale.US, "%.2f", short.stats.tokensPerSecond)}")
                appendLine("medium: ttftMs=${medium.stats.timeToFirstTokenMs} " +
                    "tokPerSec=${String.format(java.util.Locale.US, "%.2f", medium.stats.tokensPerSecond)}")
            }
            K5bArtifacts.writeK7aText(context, "k7a_engine_stats.txt", report)
            assertNotEquals(0L, engine.loadMs)
            assertTrue(short.stats.promptTokens > 0)
            assertTrue(short.stats.outputTokens > 0)
            assertTrue(short.stats.timeToFirstTokenMs >= 0)
            assertTrue(medium.stats.promptTokens > short.stats.promptTokens)
        } finally {
            engine.free()
        }
    }

    private suspend fun runEngine(
        engine: LlamaEngine,
        prompt: String,
        maxTokens: Int
    ): String {
        val builder = StringBuilder()
        val result = engine.generate(prompt = prompt, maxTokens = maxTokens) { piece ->
            builder.append(piece)
        }
        assertTrue("generation should complete when not cancelled", result.completed)
        // EOS may end a run early; both runs see the same behaviour though.
        assertTrue(result.stats.outputTokens in 1..maxTokens)
        return builder.toString()
    }
}
