package com.medai.assistant.k5b

import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.requestFocus
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.medai.assistant.ask.AskState
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Stage K5d: Real-keyboard full-device screenshots (UiAutomator captures IME + system bars).
 *
 * Captures 3 distinct states:
 * 1. 01_empty_keyboard_open: Empty state with keyboard open.
 * 2. 02_results_keyboard_closed: Results state with keyboard closed.
 * 3. 03_long_question_keyboard_open: Long question typed (3 lines) with keyboard open.
 */
@RunWith(AndroidJUnit4::class)
class K5dRealKeyboardScreenshotsTest : K5bUiTestBase() {

    @Test
    fun state01EmptyKeyboardOpen() {
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("أسئلة أمثلة").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("ask_input").performClick()
        composeRule.onNodeWithTag("ask_input").requestFocus()
        showKeyboard()
        assertTrue("IME must be visible", imeVisible())
        Thread.sleep(1500)
        composeRule.waitForIdle()
        screenshotV3("01_empty_keyboard_open")
    }

    @Test
    fun state02ResultsKeyboardClosed() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        composeRule.waitUntil(120_000) {
            composeRule.onAllNodes(hasTagPrefix("result_card_")).fetchSemanticsNodes().size == 3
        }
        waitForImeHidden()
        waitForResultsScrollToSettle()
        Thread.sleep(1000)
        composeRule.waitForIdle()
        screenshotV3("02_results_keyboard_closed")
    }

    @Test
    fun state03LongQuestionKeyboardOpen() {
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("أسئلة أمثلة").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("ask_input").performClick()
        composeRule.onNodeWithTag("ask_input").requestFocus()
        composeRule.onNodeWithTag("ask_input").performTextClearance()
        val longQuestion = "What are the clinical diagnostic criteria, differential diagnosis, and recommended first-line antimicrobial treatment options for bacterial vaginosis in non-pregnant patients?"
        composeRule.onNodeWithTag("ask_input").performTextInput(longQuestion)
        showKeyboard()
        assertTrue("IME must be visible", imeVisible())
        Thread.sleep(1500)
        composeRule.waitForIdle()
        screenshotV3("03_long_question_keyboard_open")
    }
}
