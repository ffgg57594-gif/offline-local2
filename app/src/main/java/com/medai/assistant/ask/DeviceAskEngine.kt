package com.medai.assistant.ask

import com.medai.assistant.data.Chunk
import com.medai.assistant.data.ChunkRepository
import com.medai.assistant.diagnostics.Diagnostics
import com.medai.assistant.embedder.OnnxEmbedder
import com.medai.assistant.gate.GateConfig
import com.medai.assistant.gate.GateDatabase
import com.medai.assistant.gate.GateDecision
import com.medai.assistant.gate.GateSignals
import com.medai.assistant.gate.GateVocab
import com.medai.assistant.search.DenseSearch
import com.medai.assistant.tokenizer.Tokenizer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.Locale

/**
 * Real question pipeline: tokenize -> embed (batch 1) -> dense top-5 ->
 * refusal gate -> top-3 passages. All heavy work runs off the main thread.
 *
 * The model, tokenizer, embedding matrix and gate database are owned by the
 * caller (AppGraph) and are reused for the whole process.
 */
class DeviceAskEngine(
    private val repository: ChunkRepository,
    private val tokenizer: Tokenizer,
    private val embedder: OnnxEmbedder,
    private val denseSearch: DenseSearch,
    private val gateVocab: GateVocab,
    private val gateConfig: GateConfig,
    private val gateDatabase: GateDatabase
) : AskEngine {

    override suspend fun answer(question: String, preset: String): AskAnswer =
        withContext(Dispatchers.Default) {
            val start = System.nanoTime()

            // Measure tokenization separately, then let embedQuery tokenize the
            // prefixed query exactly as the reference pipeline does.
            tokenizer.encode(OnnxEmbedder.QUERY_PREFIX + question, OnnxEmbedder.MAX_LENGTH)
            val tokenized = System.nanoTime()

            val queryVector = embedder.embedQuery(question)
            val embedded = System.nanoTime()

            val denseHits = denseSearch.search(queryVector, k = 5)
            val searched = System.nanoTime()

            val top3Hits = denseHits.take(3)
            require(top3Hits.isNotEmpty()) { "The embedding matrix returned no results" }

            val signals = GateSignals.compute(
                question = question,
                top3ChunkIds = top3Hits.map { it.chunkId },
                database = gateDatabase,
                vocab = gateVocab
            )
            val gatePreset = gateConfig.preset(preset)
            val s1 = top3Hits.first().score.toDouble()
            val accepted = GateDecision.accept(
                s1Top1 = s1,
                s3CovTop3 = signals.s3CovTop3,
                s4Unknown = signals.s4Unknown,
                preset = gatePreset
            )
            val gated = System.nanoTime()

            val chunks = repository.getByIds(top3Hits.map { it.chunkId })
            val passages = top3Hits.mapIndexedNotNull { index, hit ->
                val chunk = chunks.firstOrNull { it.id == hit.chunkId }
                    ?: return@mapIndexedNotNull null
                val shown = chunk.displayText
                val (position, total) = repository.getPositionInBook(chunk.id) ?: (0 to 0)
                Diagnostics.lastBookRawName = chunk.bookName
                Passage(
                    chunkId = chunk.id,
                    rank = index + 1,
                    bookName = chunk.bookName,
                    page = chunk.page,
                    section = chunk.section,
                    text = shown,
                    score = hit.score.toDouble(),
                    positionInBook = position,
                    totalInBook = total,
                    highlightRanges = PassageText.highlightRanges(
                        text = shown,
                        stems = signals.stems,
                        stemmer = { token -> gateDatabase.stem(token.lowercase(Locale.ROOT)) }
                    )
                )
            }

            AskAnswer(
                question = question,
                top3 = passages,
                decision = AskDecision(
                    accepted = accepted,
                    preset = preset,
                    s1 = s1,
                    s3 = signals.s3CovTop3,
                    s4 = signals.s4Unknown,
                    gateAvailable = true,
                    gateError = null
                ),
                timings = AskTiming(
                    tokenizeMs = (tokenized - start) / 1_000_000,
                    embedMs = (embedded - tokenized) / 1_000_000,
                    searchMs = (gated - embedded) / 1_000_000,
                    totalMs = (gated - start) / 1_000_000,
                    gateSignalsMs = (gated - searched) / 1_000_000
                ),
                stems = signals.stems
            )
        }

    override suspend fun neighbour(chunkId: Int, delta: Int): Chunk? =
        withContext(Dispatchers.IO) {
            repository.getNeighbour(chunkId, delta)
        }
}
