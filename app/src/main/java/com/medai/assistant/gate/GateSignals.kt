package com.medai.assistant.gate

data class GateSignalResult(
    val stems: List<String>,
    val unknownStems: List<String>,
    val s3CovTop3: Double,
    val s4Unknown: Int,
    val top3ChunkIds: List<Int>
)

/**
 * Refusal-gate signals s3 and s4, copied from `scripts/gate_signals.py`.
 *
 * s3 = number of content stems found in the top-3 chunks / number of stems
 *      (0.0 when there are no stems).
 * s4 = number of content stems whose corpus document frequency is zero.
 */
object GateSignals {
    fun compute(
        question: String,
        top3ChunkIds: List<Int>,
        database: GateDatabase,
        vocab: GateVocab
    ): GateSignalResult {
        val stems = ContentStems.contentStems(question, vocab, database)
        var hits = 0
        var unknownCount = 0
        val unknown = ArrayList<String>()

        for (stem in stems) {
            val df = database.docFreq(stem)
            val inTop3 = top3ChunkIds.any { chunkId ->
                database.chunkContainsStem(chunkId, stem)
            }
            if (inTop3) {
                hits++
            }
            if (df == 0) {
                unknownCount++
                unknown.add(stem)
            }
        }

        val s3 = if (stems.isEmpty()) 0.0 else hits.toDouble() / stems.size.toDouble()
        return GateSignalResult(
            stems = stems,
            unknownStems = unknown,
            s3CovTop3 = s3,
            s4Unknown = unknownCount,
            top3ChunkIds = top3ChunkIds
        )
    }
}
