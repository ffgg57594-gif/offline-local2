package com.offlinemedical.chat.tokenizer

import org.json.JSONObject

class Tokenizer(private val json: String) {
    private val vocab: Map<String, Int> = parseVocab(json)
    fun encode(text: String): IntArray = text.split(Regex("\\s+")).map { vocab[it] ?: 0 }.toIntArray()
    fun decode(ids: IntArray): String = ids.map { id -> vocab.entries.firstOrNull { it.value == id }?.key ?: "" }.joinToString(" ")
    companion object {
        private fun parseVocab(json: String): Map<String, Int> {
            return try { JSONObject(json).getJSONObject("model").getJSONObject("vocab").let { o -> o.keys().asSequence().associateWith { o.getInt(it) } } }
            catch (e: Exception) { emptyMap() }
        }
    }
}
