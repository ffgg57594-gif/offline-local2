package com.medai.assistant.k5b

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.doubleClick
import androidx.compose.ui.test.onAllNodes
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import com.medai.assistant.ask.AskState
import com.medai.assistant.ask.GATE_REFUSAL_SENTENCE
import com.medai.assistant.ask.Passage
import com.medai.assistant.ask.PassageText
import com.medai.assistant.diagnostics.Diagnostics
import com.medai.assistant.k4d.DeviceReferenceParsers
import com.medai.assistant.k4d.DeviceTestRuntime
import com.medai.assistant.runtime.AppGraph
import com.medai.assistant.ui.EXAMPLE_QUESTIONS
import com.medai.assistant.ui.UiOverrides
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * K5b-C: 12 Compose UI cases against the real Activity, model and gate on the
 * API 34 emulator. Every case saves a PNG screenshot.
 */
@RunWith(AndroidJUnit4::class)
class K5bUiLightTest : K5bUiTestBase() {

    private val referenceRows by lazy {
        DeviceReferenceParsers.parseCsv(DeviceTestRuntime.testAssetText("retrieval_top5.csv"))
    }

    private fun row(group: String, id: Int): Map<String, String> =
        referenceRows.first { it["group"] == group && it["id"] == id.toString() }

    private fun topPassage(state: AskState.Results): Passage =
        state.top3.firstOrNull() ?: error("the device pipeline returned no passages")

    private fun waitForSheetCitation(expected: String) {
        composeRule.waitUntil(30_000) {
            try {
                composeRule.onNodeWithTag("sheet_citation").assertTextEquals(expected)
                true
            } catch (_: AssertionError) {
                false
            }
        }
    }

    private fun waitForSheetNavigationEnabled() {
        composeRule.waitUntil(30_000) {
            try {
                composeRule.onNodeWithTag("sheet_next").assertIsEnabled()
                composeRule.onNodeWithTag("sheet_prev").assertIsEnabled()
                true
            } catch (_: AssertionError) {
                false
            }
        }
    }

    @Test
    fun case01EmptyStateShowsFourExampleQuestions() {
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("أسئلة أمثلة").fetchSemanticsNodes().isNotEmpty()
        }
        for (index in EXAMPLE_QUESTIONS.indices) {
            composeRule.onNodeWithTag("example_$index").assertIsDisplayed()
        }
        assertTagCount("example_", 4)
        screenshot("state1_empty_light")
        K5bArtifacts.writeText(
            context,
            "diagnostics.txt",
            Diagnostics.buildReport(context)
        )
    }

    @Test
    fun case02ExampleTapFillsTheInput() {
        composeRule.onNodeWithTag("example_0").performClick()
        composeRule.onNodeWithTag("ask_input").assertTextEquals(EXAMPLE_QUESTIONS[0])
        screenshot("case02_example_fills_light")
    }

    @Test
    fun case03BacterialVaginosisShowsThreeCardsAndPage261() {
        val expected = row("in", 44)
        val referencePage = expected.getValue("rank_1_page").toInt()

        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = topPassage(state as AskState.Results)
        composeRule.waitUntil(120_000) {
            composeRule.onAllNodes(hasTagPrefix("result_card_")).fetchSemanticsNodes().size == 3
        }
        assertTagCount("result_card_", 3)
        assertEquals("reference top card must cite page 261", 261, referencePage)
        assertEquals(
            "device top card page must match the Python reference",
            referencePage,
            top.page
        )
        val citation = PassageText.citation(top.bookName, top.page)
        composeRule.onNodeWithTag("citation_${top.chunkId}").assertTextEquals(citation)
        assertTrue("citation must contain page 261: $citation", citation.contains("صفحة 261"))
        screenshot("state3_results_light")
    }

    @Test
    fun case04CitationSheetPreviousNextAndClose() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = topPassage(state as AskState.Results)
        val repository = AppGraph.requireResources().repository
        val previous = repository.getNeighbour(top.chunkId, -1)
            ?: error("missing previous chunk")
        val next = repository.getNeighbour(top.chunkId, 1)
            ?: error("missing next chunk")
        val citation = PassageText.citation(top.bookName, top.page)

        composeRule.onNodeWithTag("citation_${top.chunkId}").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("sheet_citation").assertTextEquals(citation)
        screenshot("state4_sheet_light")

        waitForSheetNavigationEnabled()
        composeRule.onNodeWithTag("sheet_next").performClick()
        waitForSheetCitation(PassageText.citation(next.bookName, next.page))

        composeRule.onNodeWithTag("sheet_prev").performClick()
        waitForSheetCitation(PassageText.citation(previous.bookName, previous.page))

        composeRule.onNodeWithTag("sheet_close").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isEmpty()
        }
    }

    @Test
    fun case05FranceRefusalHidesPassagesUntilRequested() {
        val state = submitWithSendButton("What is the capital of France?")
        assertTrue("expected Rejected, got $state", state is AskState.Rejected)
        composeRule.onNodeWithTag("refusal_text").assertTextEquals(GATE_REFUSAL_SENTENCE)
        assertTagCount("result_card_", 0)
        assertTagCount("citation_", 0)
        screenshot("state5_refusal_light")

        composeRule.onNodeWithTag("show_nearest_button").performClick()
        composeRule.waitUntil(60_000) {
            composeRule.onAllNodes(hasTagPrefix("result_card_")).fetchSemanticsNodes().size == 3
        }
        assertTagCount("result_card_", 3)
        assertTagCount("citation_", 3)
    }

    @Test
    fun case06StrictPresetPersistsAfterActivityRecreation() {
        openSettings()
        composeRule.onNodeWithTag("preset_strict").performClick()
        composeRule.waitUntil(30_000) {
            viewModel().settings.value.preset == "strict"
        }
        composeRule.onNodeWithTag("settings_close").performClick()

        composeRule.activityRule.scenario.recreate()
        composeRule.waitForIdle()
        openSettings()
        composeRule.onNodeWithTag("preset_strict").assertIsSelected()
        screenshot("case06_strict_persisted_light")
        composeRule.onNodeWithTag("settings_close").performClick()
    }

    @Test
    fun case07RecreationReusesLoadedModelAndKeepsAnswer() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val loadsBefore = Diagnostics.modelLoadCount
        val question = (state as AskState.Results).question

        composeRule.activityRule.scenario.recreate()
        composeRule.waitForIdle()
        composeRule.waitUntil(60_000) {
            viewModel().state.value is AskState.Results
        }
        assertEquals(
            "recreating the Activity must not load the model again",
            1,
            Diagnostics.modelLoadCount
        )
        assertEquals(loadsBefore, Diagnostics.modelLoadCount)
        waitForUiText(question)
        screenshot("case07_recreated_light")
    }

    @Test
    fun case08DoubleTapOnSendRunsOneSearch() {
        val before = Diagnostics.searchCount
        composeRule.onNodeWithTag("ask_input").performClick()
        composeRule.onNodeWithTag("ask_input").performTextInput("What causes bacterial vaginosis?")
        composeRule.onNodeWithTag("send_button").performTouchInput { doubleClick() }
        val state = awaitTerminalState()
        assertTrue("expected Results, got $state", state is AskState.Results)
        assertEquals(
            "double tap on Send must run exactly one search",
            before + 1,
            Diagnostics.searchCount
        )
        screenshot("case08_double_tap_light")
    }

    @Test
    fun case09ImeSendActionSubmits() {
        val before = Diagnostics.searchCount
        val state = submitWithIme("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        assertEquals("IME Send must submit one search", before + 1, Diagnostics.searchCount)
        screenshot("case09_ime_send_light")
    }

    @Test
    fun case10FourLineInputGrowsAndStaysAboveKeyboard() {
        composeRule.onNodeWithTag("ask_input").performClick()
        val singleLineHeight = composeRule.onNodeWithTag("ask_input")
            .fetchSemanticsNode().size.height
        composeRule.onNodeWithTag("ask_input").performTextInput(
            "line one\nline two\nline three\nline four"
        )
        showKeyboard()
        composeRule.waitForIdle()
        val grownHeight = composeRule.onNodeWithTag("ask_input").fetchSemanticsNode().size.height
        assertTrue(
            "4-line input must grow (was $singleLineHeight, now $grownHeight)",
            grownHeight > singleLineHeight
        )
        assertTrue("the keyboard must be visible for this test", imeVisible())
        assertFullyDisplayedAboveIme("send_button")
        screenshot("case10_four_lines_keyboard_light")
    }

    @Test
    fun case11FontScale13AndDarkModeNoClippedText() {
        // This case runs at the worst combination: dark mode + font scale 1.3.
        UiOverrides.forceDark = true
        UiOverrides.fontScale = 1.3f
        composeRule.activityRule.scenario.recreate()
        composeRule.waitForIdle()
        awaitModelReady()

        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = topPassage(state as AskState.Results)
        composeRule.onNodeWithTag("citation_${top.chunkId}").assertIsDisplayed()
        assertFullyDisplayedAboveIme("send_button")
        screenshot("case11_no_clipping_font1.3_dark")
    }

    @Test
    fun case12EnglishPassageKeepsLtrDirectionInsideRtlLayout() {
        submitWithSendButton("What causes bacterial vaginosis?")
        composeRule.waitUntil(60_000) {
            composeRule.onAllNodes(
                hasTagPrefix("passage_body_") and hasTagSuffix("_ltr")
            ).fetchSemanticsNodes().isNotEmpty()
        }
        assertTrue(
            "an English passage must keep an LTR passage block",
            composeRule.onAllNodes(hasTagPrefix("passage_body_") and hasTagSuffix("_ltr"))
                .fetchSemanticsNodes().isNotEmpty()
        )
        screenshot("case12_ltr_passage_light")
    }
}
