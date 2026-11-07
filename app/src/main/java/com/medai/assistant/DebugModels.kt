package com.medai.assistant

/** Timing block used by the diagnostics report and the debug screen. */
data class SearchTiming(
    val tokenizeMs: Long,
    val embedMs: Long,
    val searchMs: Long,
    val totalMs: Long,
    /** -1 when the refusal-gate signals were not part of this request. */
    val gateSignalsMs: Long = -1L
)
