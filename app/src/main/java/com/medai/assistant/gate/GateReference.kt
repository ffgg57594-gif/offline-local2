package com.medai.assistant.gate

import java.io.File

data class GateReferenceRow(
    val group: String,
    val cls: String,
    val id: Int,
    val question: String,
    val answerable: Boolean,
    val s1Top1: Double,
    val s2Margin: Double,
    val s3CovTop3: Double,
    val s4Unknown: Int,
    val s5RareCovTop3: Double,
    val balancedDecision: Boolean,
    val strictDecision: Boolean
)

/** Loader for the Python-generated `assets/gate_reference.json`. */
object GateReference {
    fun load(file: File): List<GateReferenceRow> = fromJson(file.readText(Charsets.UTF_8))

    fun fromJson(json: String): List<GateReferenceRow> {
        return Json.parse(json).asArray().map { element ->
            val obj = element.asObject()
            val signals = obj["signals"]?.asObject() ?: error("gate_reference row is missing 'signals'")
            val decisions = obj["decisions"]?.asObject() ?: error("gate_reference row is missing 'decisions'")
            GateReferenceRow(
                group = obj["group"]?.asString() ?: "",
                cls = obj["cls"]?.asString() ?: "",
                id = obj["id"]?.asInt() ?: error("gate_reference row is missing 'id'"),
                question = obj["question"]?.asString() ?: "",
                answerable = obj["answerable"]?.asBoolean() ?: false,
                s1Top1 = signals["s1_top1"]?.asDouble() ?: 0.0,
                s2Margin = signals["s2_margin"]?.asDouble() ?: 0.0,
                s3CovTop3 = signals["s3_cov_top3"]?.asDouble() ?: 0.0,
                s4Unknown = signals["s4_unknown"]?.asInt() ?: 0,
                s5RareCovTop3 = signals["s5_rare_cov_top3"]?.asDouble() ?: -1.0,
                balancedDecision = decisions["balanced"]?.asBoolean() ?: false,
                strictDecision = decisions["strict"]?.asBoolean() ?: false
            )
        }
    }
}
