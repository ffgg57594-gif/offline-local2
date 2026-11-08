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

/** K5c item 4: the citation sheet in light mode at font scale 1.3. */
@RunWith(AndroidJUnit4::class)
class K5cUiFontScaleSheetTest : K5bUiTestBase() {

    override val forceDark: Boolean = false
    override val fontScale: Float = 1.3f

    @Test
    fun citationSheetTopAndBottomFont13Light() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = (state as AskState.Results).top3.maxByOrNull { it.text.length }
            ?: error("the device pipeline returned no passages")
        composeRule.onNodeWithTag("citation_${top.chunkId}").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("في الكتاب", substring = true)
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("sheet_prev").assertIsDisplayed()
        composeRule.onNodeWithTag("sheet_next").assertIsDisplayed()
        screenshot("08_sheet_top_font13_light")

        scrollSheetToBottom()
        composeRule.onNodeWithTag("sheet_prev").assertIsDisplayed()
        composeRule.onNodeWithTag("sheet_next").assertIsDisplayed()
        screenshot("09_sheet_bottom_font13_light")
    }
}
