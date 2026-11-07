package com.medai.assistant.gate

import java.io.File
import java.text.Normalizer
import java.util.Locale
import java.util.regex.Pattern

/**
 * Vocabulary and normalization rules for the refusal gate.
 *
 * Produced by `scripts/write_gate_vocab.py` from the Python source of truth
 * (`keyword_builder.STOPWORDS`, `keyword_builder.NON_CONTENT_WORDS`,
 * `text_normalize.normalize_text`, `gate_signals.HYPHEN_COMPOUNDS`,
 * `gate_signals.FTS5_TOKENIZER`).
 */
data class GateVocab(
    val stopwords: Set<String>,
    val nonContentWords: Set<String>,
    val variantMap: Map<String, String>,
    val zeroWidthChars: List<String>,
    val hyphenLikeChars: List<String>,
    val possessivePattern: Regex,
    val tokenPattern: Regex,
    val hyphenCompounds: Map<String, List<String>>,
    val ftsTokenizer: String,
    val unicodeForm: String = "NFKC"
) {
    private val whitespacePattern: Regex = unicodeRegex("\\s+")
    private val hyphenCharSet: Set<Char> = hyphenLikeChars.mapNotNull { it.firstOrNull() }.toSet()
    private val variantPatterns: List<Pair<Regex, String>> = variantMap.entries
        .sortedByDescending { it.key.length }
        .map { (source, target) ->
            unicodeRegex("\\b" + Pattern.quote(source) + "\\b") to target
        }

    /** Mirrors `text_normalize.normalize_text` exactly. */
    fun normalize(text: String): String {
        var value = Normalizer.normalize(text, Normalizer.Form.NFKC)
        for (zeroWidth in zeroWidthChars) {
            value = value.replace(zeroWidth, "")
        }
        value = value.lowercase(Locale.ROOT)
        val unified = StringBuilder(value.length)
        for (c in value) {
            unified.append(if (c in hyphenCharSet) '-' else c)
        }
        value = unified.toString()
        for ((pattern, target) in variantPatterns) {
            value = pattern.replace(value) { target }
        }
        value = whitespacePattern.replace(value, " ").trim()
        return value
    }

    /**
     * Normalize, strip possessive 's / ’s, and tokenize with the same
     * Unicode-aware `\w+` pattern as Python's `re.findall(r"\w+", norm)`.
     */
    fun contentTokens(question: String): List<String> {
        val normalized = normalize(question)
        val withoutPossessive = possessivePattern.replace(normalized, "")
        return tokenPattern.findAll(withoutPossessive).map { it.value }.toList()
    }

    companion object {
        fun load(file: File): GateVocab = fromJson(file.readText(Charsets.UTF_8))

        fun fromJson(json: String): GateVocab {
            val root = Json.parse(json).asObject()
            val normalization = root["normalization"]?.asObject()
                ?: error("gate_vocab.json is missing 'normalization'")

            val stopwords = root["stopwords"]?.asArray()
                ?.map { it.asString() }?.toSet()
                ?: error("gate_vocab.json is missing 'stopwords'")
            val nonContentWords = root["non_content_words"]?.asArray()
                ?.map { it.asString() }?.toSet()
                ?: emptySet()

            val variantMap = root["variant_map"]?.asObject()
                ?.mapValues { it.value.asString() }
                ?: emptyMap()

            val zeroWidthChars = normalization["zero_width_chars"]?.asArray()
                ?.map { it.asString() }
                ?: emptyList()
            val hyphenLikeChars = normalization["hyphen_like_chars"]?.asArray()
                ?.map { it.asString() }
                ?: emptyList()

            val possessive = normalization["possessive_pattern"]?.asString()
                ?: "['\u2019]s\\b"
            val tokenPattern = normalization["token_pattern_kotlin"]?.asString()
                ?: normalization["token_pattern_python"]?.asString()
                ?: "\\w+"

            val hyphenCompounds = normalization["hyphen_compounds"]?.asObject()
                ?.mapValues { (_, value) -> value.asArray().map { it.asString() } }
                ?: emptyMap()

            val ftsTokenizer = root["fts_tokenizer"]?.asString()
                ?: "porter unicode61 remove_diacritics 2"

            val unicodeForm = normalization["unicode_form"]?.asString() ?: "NFKC"

            return GateVocab(
                stopwords = stopwords,
                nonContentWords = nonContentWords,
                variantMap = variantMap,
                zeroWidthChars = zeroWidthChars,
                hyphenLikeChars = hyphenLikeChars,
                possessivePattern = unicodeRegex(possessive),
                tokenPattern = unicodeRegex(tokenPattern),
                hyphenCompounds = hyphenCompounds,
                ftsTokenizer = ftsTokenizer,
                unicodeForm = unicodeForm
            )
        }

        private fun unicodeRegex(pattern: String): Regex =
            Pattern.compile(pattern, Pattern.UNICODE_CHARACTER_CLASS).toRegex()
    }
}
