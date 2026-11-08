package com.medai.assistant.design

/**
 * Switchable design direction for STAGE UI-A:
 * - [PAPER_INK]: "ورق وحبر" — Warm paper background, ink text, deep teal accent, amber marker highlight, hairline borders.
 * - [CLINICAL_NIGHT]: "ليل سريري" — Cool near-white, deep ink-navy dark, medical blue-green accent, coral rejection/alert.
 */
enum class DesignDirection {
    PAPER_INK,
    CLINICAL_NIGHT
}

object DesignConfig {
    /**
     * Switchable with one constant as required by STAGE UI-A item 2.
     */
    var activeDirection: DesignDirection = DesignDirection.PAPER_INK
}
