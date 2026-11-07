package com.medai.assistant.gate

import java.io.File
import java.util.Locale

data class GatePreset(
    val t1: Double,
    val t3: Double,
    val k: Int
)

/**
 * Refusal-gate preset parameters loaded from `assets/gate_config.json`.
 * Balanced and strict presets are exactly the values fitted by
 * `scripts/fit_gate.py`.
 */
data class GateConfig(
    val balanced: GatePreset,
    val strict: GatePreset,
    val margin: Double
) {
    fun preset(name: String): GatePreset = when (name.lowercase(Locale.ROOT)) {
        "balanced" -> balanced
        "strict" -> strict
        else -> error("Unknown gate preset '$name' (expected balanced or strict)")
    }

    companion object {
        fun load(file: File): GateConfig = fromJson(file.readText(Charsets.UTF_8))

        fun fromJson(json: String): GateConfig {
            val root = Json.parse(json).asObject()
            val balanced = parsePreset(root["balanced"] ?: error("gate_config.json is missing 'balanced'"))
            val strict = parsePreset(root["strict"] ?: error("gate_config.json is missing 'strict'"))
            val margin = root["margin"]?.asDouble() ?: 0.01
            return GateConfig(balanced = balanced, strict = strict, margin = margin)
        }

        private fun parsePreset(value: JsonValue): GatePreset {
            val obj = value.asObject()
            return GatePreset(
                t1 = obj["t1"]?.asDouble() ?: error("gate preset is missing 't1'"),
                t3 = obj["t3"]?.asDouble() ?: error("gate preset is missing 't3'"),
                k = obj["k"]?.asInt() ?: error("gate preset is missing 'k'")
            )
        }
    }
}

/**
 * Pure decision function: `accept = s1 + eps >= t1 and s3 + eps >= t3 and s4 <= k`.
 * Copied from `scripts/gate_rule.py`. The 1e-6 epsilon absorbs float rounding
 * differences between the Python pipeline and the JVM (for example s3 = 4/7).
 */
object GateDecision {
    const val EPSILON = 1e-6

    fun accept(s1Top1: Double, s3CovTop3: Double, s4Unknown: Int, preset: GatePreset): Boolean {
        return s1Top1 + EPSILON >= preset.t1 &&
            s3CovTop3 + EPSILON >= preset.t3 &&
            s4Unknown <= preset.k
    }
}
