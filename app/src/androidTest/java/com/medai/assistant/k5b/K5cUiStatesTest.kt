package com.medai.assistant.k5b

import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.medai.assistant.ask.AskState
import com.medai.assistant.ui.UiOverrides
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** K5c states that are hard to catch or need the diagnostics toggle. */
@RunWith(AndroidJUnit4::class)
class K5cUiStatesTest : K5bUiTestBase() {

    @Test
    fun loadingSearchingStateIsVisibleAndNotEmpty() {
        UiOverrides.searchDelayMs = 10_000L
        try {
            composeRule.onNodeWithTag("ask_input").performClick()
            composeRule.onNodeWithTag("ask_input")
                .performTextInput("What causes bacterial vaginosis?")
            composeRule.onNodeWithTag("send_button").performClick()
            composeRule.waitUntil(30_000) {
                viewModel().state.value is AskState.Searching
            }
            composeRule.waitUntil(30_000) {
                composeRule.onAllNodes(hasTagPrefix("searching_state"))
                    .fetchSemanticsNodes().isNotEmpty()
            }
            waitForImeHidden()
            screenshot("12_loading_searching_light")
            val state = awaitTerminalState()
            assertTrue("expected Results, got $state", state is AskState.Results)
        } finally {
            UiOverrides.searchDelayMs = 0L
        }
    }

    @Test
    fun cosineScoreIsHiddenUntilDiagnosticsMode() {
        val first = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $first", first is AskState.Results)
        assertEquals(
            "cosine score must be hidden outside diagnostics mode",
            0,
            composeRule.onAllNodes(hasTagPrefix("score_")).fetchSemanticsNodes().size
        )

        openSettings()
        composeRule.onNodeWithTag("show_timings_switch").performScrollTo().performClick()
        composeRule.waitUntil(30_000) {
            viewModel().settings.value.showTimings
        }
        composeRule.onNodeWithTag("settings_close").performScrollTo().performClick()

        val second = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $second", second is AskState.Results)
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodes(hasTagPrefix("score_")).fetchSemanticsNodes().isNotEmpty()
        }
        assertTrue(
            "diagnostics mode must show the cosine score",
            composeRule.onAllNodes(hasTagPrefix("score_")).fetchSemanticsNodes().isNotEmpty()
        )
    }
}
