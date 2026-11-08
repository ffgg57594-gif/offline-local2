package com.medai.assistant.k5b

import androidx.compose.ui.test.onAllNodesWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.medai.assistant.ask.AskState
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** K5c required dark states: empty and results with the keyboard closed. */
@RunWith(AndroidJUnit4::class)
class K5bUiDarkScreenshotsTest : K5bUiTestBase() {

    override val forceDark: Boolean = true

    @Test
    fun state01EmptyDark() {
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("أسئلة أمثلة").fetchSemanticsNodes().isNotEmpty()
        }
        screenshot("02_empty_dark")
    }

    @Test
    fun state03ResultsDarkKeyboardClosed() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        composeRule.waitUntil(120_000) {
            composeRule.onAllNodes(hasTagPrefix("result_card_")).fetchSemanticsNodes().size == 3
        }
        waitForImeHidden()
        screenshot("04_results_dark_keyboard_closed")
    }
}
