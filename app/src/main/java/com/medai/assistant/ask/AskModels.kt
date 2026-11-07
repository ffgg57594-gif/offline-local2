package com.medai.assistant.ask

import com.medai.assistant.data.Chunk

/** Exact refusal sentence required by the product specification. */
const val GATE_REFUSAL_SENTENCE =
    "هذه المعلومة غير مذكورة في الكتب الطبية المدمجة في التطبيق."

/** One ranked passage shown on the answer screen. */
data class Passage(
    val chunkId: Int,
    val rank: Int,
    val bookName: String,
    val page: Int,
    val section: String,
    val text: String,
    /** Ranges in [text] that share a gate content stem with the question. */
    val highlightRanges: List<IntRange> = emptyList()
)

data class AskDecision(
    val accepted: Boolean,
    val preset: String,
    val s1: Double,
    val s3: Double,
    val s4: Int,
    val gateAvailable: Boolean,
    val gateError: String?
)

data class AskTiming(
    val tokenizeMs: Long,
    val embedMs: Long,
    val searchMs: Long,
    val totalMs: Long,
    val gateSignalsMs: Long = -1L
)

data class AskAnswer(
    val question: String,
    val top3: List<Passage>,
    val decision: AskDecision,
    val timings: AskTiming,
    val stems: List<String>
)

/** Contract implemented by the real device pipeline and by JVM fakes. */
interface AskEngine {
    suspend fun answer(question: String, preset: String): AskAnswer
    suspend fun neighbour(chunkId: Int, delta: Int): Chunk?
}

/** Every user-visible state of the question screen. */
sealed interface AskState {
    data class Installing(
        val fileName: String,
        val doneBytes: Long,
        val totalBytes: Long
    ) : AskState

    data object LoadingModel : AskState

    data object Ready : AskState

    data class Searching(val question: String) : AskState

    data class Results(
        val question: String,
        val top3: List<Passage>,
        val decision: AskDecision,
        val timings: AskTiming,
        val stems: List<String>
    ) : AskState

    data class Rejected(
        val question: String,
        val refusal: String,
        val top3: List<Passage>,
        val decision: AskDecision,
        val timings: AskTiming,
        val stems: List<String>
    ) : AskState

    data class Error(val message: String) : AskState
}
