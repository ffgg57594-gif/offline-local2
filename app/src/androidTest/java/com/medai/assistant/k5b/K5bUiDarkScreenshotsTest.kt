package com.medai.assistant.k5b

import androidx.compose.ui.test.onAllNodes
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import com.medai.assistant.ask.AskState
import com.medai.assistant.ask.GATE_REFUSAL_SENTENCE
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** K5b-C screenshots for states 1, 3, 4 and 5 in dark mode. */
@RunWith(AndroidJUnit4::class)
class K5bUiDarkScreenshotsTest : K5bUiTestBase() {

    override val forceDark: Boolean = true

    @Test
    fun state01EmptyDark() {
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("أسئلة أمثلة").fetchSemanticsNodes().isNotEmpty()
        }
        screenshot("state1_empty_dark")
    }

    @Test
    fun state03ResultsDark() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        composeRule.waitUntil(120_000) {
            composeRule.onAllNodes(hasTagPrefix("result_card_")).fetchSemanticsNodes().size == 3
        }
        screenshot("state3_results_dark")
    }

    @Test
    fun state04CitationSheetDark() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = (state as AskState.Results).top3.first()
        composeRule.onNodeWithTag("citation_${top.chunkId}").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isNotEmpty()
        }
        screenshot("state4_sheet_dark")
    }

    @Test
    fun state05RefusalDark() {
        val state = submitWithSendButton("What is the capital of France?")
        assertTrue("expected Rejected, got $state", state is AskState.Rejected)
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText(GATE_REFUSAL_SENTENCE).fetchSemanticsNodes().isNotEmpty()
        }
        screenshot("state5_refusal_dark")
    }
}
