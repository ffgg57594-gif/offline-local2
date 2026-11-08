package com.medai.assistant.ui

/**
 * K5c dark-theme tokens measured by `scripts/check_contrast.py` and
 * `ContrastTest`.
 *
 * The values are the Material 3 baseline dark tokens, pinned here so the CI
 * contrast check reads exactly the colours the Compose theme uses instead of
 * guessing framework defaults.
 */
object UiColors {
    /** Passage highlight background and text in dark mode. */
    const val HIGHLIGHT_BACKGROUND_DARK = 0xFF4A4458
    const val HIGHLIGHT_TEXT_DARK = 0xFFE8DEF8

    /** Page/citation chip background and text in dark mode. */
    const val CITATION_CHIP_BACKGROUND_DARK = 0xFF4F378B
    const val CITATION_CHIP_TEXT_DARK = 0xFFEADDFF
}
