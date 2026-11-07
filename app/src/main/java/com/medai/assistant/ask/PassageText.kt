package com.medai.assistant.ask

import com.medai.assistant.Patterns
import java.util.Locale

data class TruncatedText(
    val text: String,
    val truncated: Boolean
)

/** Pure text rules used by the result card and its JVM tests. */
object PassageText {
    const val MAX_PREVIEW_CHARS = 350

    /** Exact citation line required by the product specification. */
    fun citation(bookName: String, page: Int): String {
        return "[المصدر: ${bookName.replace('_', ' ')} - صفحة $page]"
    }

    /**
     * First 350 characters, cut backwards to a word boundary when possible.
     * If the whole text fits, [TruncatedText.truncated] is false.
     */
    fun truncateAtWord(
        text: String,
        maxChars: Int = MAX_PREVIEW_CHARS
    ): TruncatedText {
        require(maxChars > 0) { "maxChars must be positive" }
        if (text.length <= maxChars) return TruncatedText(text, false)

        val hardCut = text.substring(0, maxChars)
        val boundary = hardCut.indexOfLast { it.isWhitespace() }
        val cut = if (boundary > 0) hardCut.substring(0, boundary).trimEnd() else hardCut
        return TruncatedText(cut, true)
    }

    /**
     * Tokenize [text] and return the ranges whose porter stem is in [stems].
     * The tokenizer ignores punctuation and splits hyphenated compounds, so
     * "blood-pressure" can match either the "blood" or "pressure" stem.
     */
    fun highlightRanges(
        text: String,
        stems: List<String>,
        stemmer: (String) -> String = { it }
    ): List<IntRange> {
        if (text.isEmpty() || stems.isEmpty()) return emptyList()
        val wanted = stems.toHashSet()
        return Patterns.TOKEN.findAll(text).mapNotNull { match ->
            val stem = stemmer(match.value.lowercase(Locale.ROOT))
            if (stem in wanted) match.range else null
        }.toList()
    }

    /**
     * A passage is laid out LTR when Latin letters are the clear majority;
     * Arabic or other scripts stay in the surrounding RTL layout.
     */
    fun isMostlyLatin(text: String): Boolean {
        var latin = 0
        var letters = 0
        for (char in text.take(400)) {
            if (!char.isLetter()) continue
            letters++
            if (char in 'A'..'Z' || char in 'a'..'z') latin++
        }
        return letters > 0 && latin * 2 >= letters
    }
}
