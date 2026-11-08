package com.medai.assistant.k5b

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.medai.assistant.ask.AskState
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** K5c: font scale 1.3 + dark mode; one screenshot for the results state. */
@RunWith(AndroidJUnit4::class)
class K5bUiFontScaleDarkTest : K5bUiTestBase() {

    override val forceDark: Boolean = true
    override val fontScale: Float = 1.3f

    @Test
    fun state03ResultsFont13Dark() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        composeRule.waitUntil(120_000) {
            composeRule.onAllNodes(hasTagPrefix("result_card_")).fetchSemanticsNodes().size == 3
        }
        waitForImeHidden()
        screenshot("05_results_font13_dark")
    }

    @Test
    fun citationSheetFooterStaysVisibleAtFont13() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = (state as AskState.Results).top3.first()
        composeRule.onNodeWithTag("citation_${top.chunkId}").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("sheet_prev").assertIsDisplayed()
        composeRule.onNodeWithTag("sheet_next").assertIsDisplayed()
    }
}
