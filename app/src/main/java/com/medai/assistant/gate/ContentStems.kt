package com.medai.assistant.gate

/**
 * Ordered content stems for one question.
 *
 * Mirrors `gate_signals.content_stems`:
 * normalize -> strip possessive -> tokenize -> expand hyphen compounds ->
 * drop non-alphabetic / single-letter / stopword tokens -> FTS5 porter stem ->
 * de-duplicate while preserving order.
 */
object ContentStems {
    fun contentStems(question: String, vocab: GateVocab, database: GateDatabase): List<String> {
        val tokens = vocab.contentTokens(question)
        val expanded = ArrayList<String>(tokens.size)
        for (token in tokens) {
            val parts = vocab.hyphenCompounds[token]
            if (parts != null) {
                expanded.addAll(parts)
            } else {
                expanded.add(token)
            }
        }

        val stems = ArrayList<String>()
        val seen = HashSet<String>()
        for (token in expanded) {
            if (token.isEmpty() || !token.all { it.isLetter() }) continue
            if (token.length < 2) continue
            if (token in vocab.stopwords) continue
            val stem = database.stem(token)
            if (stem.isNotEmpty() && seen.add(stem)) {
                stems.add(stem)
            }
        }
        return stems
    }
}
