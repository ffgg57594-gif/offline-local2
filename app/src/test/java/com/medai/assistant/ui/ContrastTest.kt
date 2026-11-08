package com.medai.assistant.ui

import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.pow

/** K5c item 10: the dark tokens must reach WCAG AA (4.5:1) for text. */
class ContrastTest {

    private fun channel(value: Int): Double {
        val srgb = value / 255.0
        return if (srgb <= 0.04045) srgb / 12.92
        else ((srgb + 0.055) / 1.055).pow(2.4)
    }

    private fun luminance(rgb: Long): Double {
        val value = rgb.toInt()
        return 0.2126 * channel((value shr 16) and 0xFF) +
            0.7152 * channel((value shr 8) and 0xFF) +
            0.0722 * channel(value and 0xFF)
    }

    private fun contrast(background: Long, text: Long): Double {
        val a = luminance(background)
        val b = luminance(text)
        return (maxOf(a, b) + 0.05) / (minOf(a, b) + 0.05)
    }

    @Test
    fun darkHighlightAndCitationChipMeetAa() {
        val highlight = contrast(
            UiColors.HIGHLIGHT_BACKGROUND_DARK,
            UiColors.HIGHLIGHT_TEXT_DARK
        )
        val chip = contrast(
            UiColors.CITATION_CHIP_BACKGROUND_DARK,
            UiColors.CITATION_CHIP_TEXT_DARK
        )
        println("dark highlight contrast: %.3f".format(highlight))
        println("dark citation chip contrast: %.3f".format(chip))
        assertTrue("highlight contrast $highlight < 4.5", highlight >= 4.5)
        assertTrue("citation chip contrast $chip < 4.5", chip >= 4.5)
    }
}
