package com.medai.assistant

/**
 * K5c display configuration for embedded books.
 *
 * The raw book name is an internal asset identifier and stays in diagnostics;
 * the UI always shows [display]. Add new books here rather than inline in the
 * Compose code.
 */
object BookTitles {
    private val DISPLAY_NAMES = mapOf(
        "425_OBG_clean_single_pages" to "Obstetrics and Gynecology Textbook"
    )

    fun display(rawName: String): String =
        DISPLAY_NAMES[rawName] ?: rawName.replace('_', ' ')
}
