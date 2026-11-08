package com.medai.assistant.k5b

import androidx.compose.ui.test.assertIsDisplayed
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

/** K5b-C: font scale 1.3 + dark mode for states 1, 3, 4, 5 and case 11. */
@RunWith(AndroidJUnit4::class)
class K5bUiFontScaleDarkTest : K5bUiTestBase() {

    override val forceDark: Boolean = true
    override val fontScale: Float = 1.3f

    @Test
    fun state01EmptyFont13Dark() {
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("أسئلة أمثلة").fetchSemanticsNodes().isNotEmpty()
        }
        screenshot("state1_empty_font1.3_dark")
    }

    @Test
    fun state03ResultsFont13Dark() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        composeRule.waitUntil(120_000) {
            composeRule.onAllNodes(hasTagPrefix("result_card_")).fetchSemanticsNodes().size == 3
        }
        screenshot("state3_results_font1.3_dark")
    }

    @Test
    fun state04CitationSheetFont13Dark() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = (state as AskState.Results).top3.first()
        composeRule.onNodeWithTag("citation_${top.chunkId}").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isNotEmpty()
        }
        screenshot("state4_sheet_font1.3_dark")
    }

    @Test
    fun state05RefusalFont13Dark() {
        val state = submitWithSendButton("What is the capital of France?")
        assertTrue("expected Rejected, got $state", state is AskState.Rejected)
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText(GATE_REFUSAL_SENTENCE).fetchSemanticsNodes().isNotEmpty()
        }
        screenshot("state5_refusal_font1.3_dark")
    }

    @Test
    fun case11Font13DarkCitationAndSendAreFullyVisible() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = (state as AskState.Results).top3.first()
        composeRule.onNodeWithTag("citation_${top.chunkId}").assertIsDisplayed()
        assertFullyDisplayedAboveIme("citation_${top.chunkId}")
        assertFullyDisplayedAboveIme("send_button")
        screenshot("state11_no_clipping_font1.3_dark")
    }
}
