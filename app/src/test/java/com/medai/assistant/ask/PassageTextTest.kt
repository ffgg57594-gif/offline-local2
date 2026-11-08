package com.medai.assistant.ask

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PassageTextTest {

    @Test
    fun citationUsesDisplayTitleAndExplicitIsolates() {
        assertEquals(
            "المصدر: \u2068book one\u2069 صفحة 42",
            PassageText.citation("book_one", 42)
        )
        assertEquals(
            "المصدر: \u2068Williams Obstetrics\u2069 صفحة 1185",
            PassageText.citation("Williams_Obstetrics", 1185)
        )
        assertEquals(
            "المصدر: \u2068Obstetrics and Gynecology Textbook\u2069 صفحة 261",
            PassageText.citation("425_OBG_clean_single_pages", 261)
        )
        assertFalse(PassageText.citation("425_OBG_clean_single_pages", 261).contains("["))
        assertFalse(PassageText.citation("425_OBG_clean_single_pages", 261).contains("]"))
    }

    @Test
    fun shortTextIsNotTruncated() {
        val result = PassageText.truncateAtWord("x".repeat(350))
        assertEquals(350, result.text.length)
        assertFalse(result.truncated)
    }

    @Test
    fun longTextIsCutAt350CharactersOnAWordBoundary() {
        val text = "alpha ".repeat(100)
        val result = PassageText.truncateAtWord(text)

        assertTrue(result.truncated)
        assertTrue(result.text.length <= PassageText.MAX_PREVIEW_CHARS)
        assertTrue(result.text.endsWith("alpha"))
        assertFalse(result.text.endsWith(" "))
        assertTrue(text.startsWith(result.text))
    }

    @Test
    fun truncationDoesNotSplitALongWord() {
        val text = "a".repeat(400)
        val result = PassageText.truncateAtWord(text)

        assertTrue(result.truncated)
        assertEquals(350, result.text.length)
        assertTrue(text.startsWith(result.text))
    }

    @Test
    fun highlightMatchesStemsCaseInsensitively() {
        val ranges = PassageText.highlightRanges(
            text = "Blood pressure control",
            stems = listOf("blood", "pressur"),
            stemmer = { token -> if (token == "pressure") "pressur" else token }
        )
        assertEquals(listOf(0..4, 6..13), ranges)
    }

    @Test
    fun highlightIgnoresPunctuationAroundWords() {
        val ranges = PassageText.highlightRanges(
            text = "Hypertension, diabetes.",
            stems = listOf("hypertens", "diabet"),
            stemmer = { token ->
                when (token) {
                    "hypertension" -> "hypertens"
                    "diabetes" -> "diabet"
                    else -> token
                }
            }
        )
        assertEquals(listOf(0..11, 14..21), ranges)
    }

    @Test
    fun highlightSplitsHyphenatedCompounds() {
        val ranges = PassageText.highlightRanges(
            text = "blood-pressure",
            stems = listOf("blood", "pressure"),
            stemmer = { it }
        )
        assertEquals(listOf(0..4, 6..13), ranges)
    }

    @Test
    fun highlightReturnsNothingForEmptyInputs() {
        assertTrue(PassageText.highlightRanges("text", emptyList()).isEmpty())
        assertTrue(PassageText.highlightRanges("", listOf("text")).isEmpty())
    }

    @Test
    fun mostlyLatinDetectsEnglishAndArabicBlocks() {
        assertTrue(PassageText.isMostlyLatin("The uterus is enlarged."))
        assertFalse(PassageText.isMostlyLatin("الرحم متضخم."))
        assertTrue(PassageText.isMostlyLatin("Pregnancy الحمل"))
    }
}
