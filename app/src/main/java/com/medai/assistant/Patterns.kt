package com.medai.assistant

import java.util.regex.Pattern

/**
 * Every regular expression used by the app lives here.
 *
 * Android's regex engine is ICU based and rejects the JVM-only
 * Unicode-character-class flag (and its inline form). Python's `\w`/`\b`/`\s`
 * are Unicode-aware by default, so that JVM-only flag used to make the desktop
 * unit tests pass while the same pattern threw on a phone.
 *
 * The patterns below spell the Unicode character classes out explicitly so the
 * JVM and Android have identical behaviour without any flag:
 *   - `\w`  -> `[\p{L}\p{M}\p{N}_]`
 *   - `\b`  -> `(?<![\p{L}\p{M}\p{N}_])` / `(?![\p{L}\p{M}\p{N}_])`
 *   - `\s`  -> `[\s\p{Z}\u001C-\u001F\u0085]`
 */
object Patterns {
    private const val WORD_CHARS = "\\p{L}\\p{M}\\p{N}_"
    private const val WORD_CLASS = "[$WORD_CHARS]"

    /** Python `re.findall(r"\w+", text)` equivalent. */
    val TOKEN: Regex = Regex("$WORD_CLASS+")

    /** Python `re.sub(r"['\u2019]s\b", "", text)` equivalent. */
    val POSSESSIVE: Regex = Regex("['\u2019]s(?!$WORD_CLASS)")

    /** Python `\s+` equivalent (includes Unicode separators). */
    val WHITESPACE: Regex = Regex("[\\s\\p{Z}\\u001C-\\u001F\\u0085]+")

    /** Collapse repeated ASCII spaces, as the tokenizer fallback did. */
    val DOUBLE_SPACE: Regex = Regex(" {2,}")

    /**
     * Python `re.sub(r"\b" + re.escape(source) + r"\b", target, text)`.
     * Lookarounds replace `\b` so no Unicode flag is needed.
     */
    fun variant(source: String): Regex =
        Regex("(?<!$WORD_CLASS)" + Pattern.quote(source) + "(?!$WORD_CLASS)")

    // ManifestParser (ASCII JSON, but centralised so there is one pattern file).
    val MANIFEST_CHUNK_COUNT: Regex = Regex("\"chunk_count\"\\s*:\\s*([0-9]+)")
    val MANIFEST_CHUNK_TEXT_SHA: Regex = Regex("\"chunk_texts_sha256\"\\s*:\\s*\"([^\"]+)\"")
    val MANIFEST_ASSET_BLOCK: Regex = Regex(
        "\\{\\s*\"name\"\\s*:\\s*\"([^\"]+)\"\\s*,\\s*\"size\"\\s*:\\s*([0-9]+)" +
            "\\s*,\\s*\"sha256\"\\s*:\\s*\"([^\"]+)\"\\s*\\}"
    )
}
