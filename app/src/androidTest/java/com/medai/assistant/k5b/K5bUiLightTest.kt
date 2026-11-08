package com.medai.assistant.k5b

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.assertIsNotFocused
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.doubleClick
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.requestFocus
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
 * K5b/K5c: 12 Compose UI cases against the real Activity, model and gate on the
 * API 34 emulator. Screenshot names are unique per distinct state; the CI
 * screenshot check rejects byte-identical images.
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

    private fun waitForSheetPosition() {
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("في الكتاب", substring = true)
                .fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun expectedPosition(chunkId: Int): String {
        val (position, total) =
            AppGraph.requireResources().repository.getPositionInBook(chunkId)
                ?: error("missing position for chunk $chunkId")
        return "فقرة $position من $total في الكتاب"
    }

    private fun waitForSheetPositionText(expected: String) {
        composeRule.waitUntil(30_000) {
            try {
                composeRule.onNodeWithTag("sheet_position").assertTextEquals(expected)
                true
            } catch (_: AssertionError) {
                false
            }
        }
    }

    @Test
    fun case01EmptyStateShowsTitleAndFourExampleCards() {
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("أسئلة أمثلة").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("اسأل عن كتابك الطبي").assertIsDisplayed()
        for (index in EXAMPLE_QUESTIONS.indices) {
            composeRule.onNodeWithTag("example_$index").assertIsDisplayed()
        }
        assertTagCount("example_", 4)
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("صفحة)", substring = true)
                .fetchSemanticsNodes().isNotEmpty()
        }
        screenshot("01_empty_light")
        K5bArtifacts.writeText(
            context,
            "diagnostics.txt",
            Diagnostics.buildReport(context)
        )
    }

    @Test
    fun case02ExampleTapClearsTheKeyboardAndFillsTheInput() {
        composeRule.onNodeWithTag("ask_input").performClick()
        composeRule.onNodeWithTag("ask_input").requestFocus()
        composeRule.onNodeWithTag("ask_input").assertIsFocused()
        showKeyboard()
        assertTrue("the keyboard must be visible before tapping a chip", imeVisible())

        composeRule.onNodeWithTag("example_0").performScrollTo().performClick()
        composeRule.waitForIdle()
        composeRule.onNodeWithTag("ask_input").assertTextEquals(EXAMPLE_QUESTIONS[0])
        composeRule.onNodeWithTag("ask_input").assertIsNotFocused()
        waitForImeHidden()
    }

    @Test
    fun case03BacterialVaginosisShowsThreeCardsAndPage261KeyboardClosed() {
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
        assertTrue("citation must isolate the Latin title", citation.contains("\u2068"))
        waitForImeHidden()
        composeRule.waitUntil(30_000) {
            try {
                assertFullyVisibleAboveInput("result_card_${top.chunkId}")
                true
            } catch (_: AssertionError) {
                false
            }
        }
        screenshot("03_results_light_keyboard_closed")
    }

    @Test
    fun case04CitationSheetPinnedHeaderFooterAndNavigation() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        // Use the longest of the three passages so the sheet really scrolls and
        // the top/bottom screenshots are guaranteed to show different content.
        val top = (state as AskState.Results).top3.maxByOrNull { it.text.length }
            ?: error("the device pipeline returned no passages")
        val repository = AppGraph.requireResources().repository
        val previous = repository.getNeighbour(top.chunkId, -1)
            ?: error("missing previous chunk")
        val next = repository.getNeighbour(top.chunkId, 1)
            ?: error("missing next chunk")
        val citation = PassageText.citation(top.bookName, top.page)

        // The longest passage is not necessarily the first card, so scroll its
        // citation chip into the viewport before injecting the tap.
        composeRule.onNodeWithTag("citation_${top.chunkId}")
            .performScrollTo()
            .performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("sheet_citation").assertTextEquals(citation)
        waitForSheetNavigationEnabled()
        waitForSheetPosition()
        waitForSheetPositionText(expectedPosition(top.chunkId))
        composeRule.onNodeWithTag("sheet_prev").assertIsDisplayed()
        composeRule.onNodeWithTag("sheet_next").assertIsDisplayed()
        screenshot("06_sheet_top_light")

        scrollSheetToBottom()
        screenshot("07_sheet_bottom_light")

        // Walk forward once, then back twice: the footer buttons must really
        // navigate (and be re-enabled after each load).
        composeRule.onNodeWithTag("sheet_next").performClick()
        waitForSheetPositionText(expectedPosition(next.id))
        waitForSheetNavigationEnabled()
        waitForSheetCitation(PassageText.citation(next.bookName, next.page))

        composeRule.onNodeWithTag("sheet_prev").performClick()
        waitForSheetPositionText(expectedPosition(top.chunkId))
        waitForSheetNavigationEnabled()
        waitForSheetCitation(citation)

        composeRule.onNodeWithTag("sheet_prev").performClick()
        waitForSheetPositionText(expectedPosition(previous.id))
        waitForSheetCitation(PassageText.citation(previous.bookName, previous.page))

        composeRule.onNodeWithTag("sheet_close").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isEmpty()
        }
    }

    @Test
    fun case05FranceRefusalCollapsedAndExpanded() {
        val state = submitWithSendButton("What is the capital of France?")
        assertTrue("expected Rejected, got $state", state is AskState.Rejected)
        composeRule.onNodeWithTag("refusal_text").assertTextEquals(GATE_REFUSAL_SENTENCE)
        assertTagCount("result_card_", 0)
        assertTagCount("citation_", 0)
        waitForImeHidden()
        screenshot("10_refusal_collapsed_light")

        composeRule.onNodeWithTag("show_nearest_button").performClick()
        composeRule.waitUntil(60_000) {
            composeRule.onAllNodes(hasTagPrefix("result_card_")).fetchSemanticsNodes().size == 3
        }
        assertTagCount("result_card_", 3)
        assertTagCount("citation_", 3)
        screenshot("11_refusal_expanded_light")
    }

    @Test
    fun case06StrictPresetSettingsSheetAndPersistence() {
        openSettings()
        composeRule.onNodeWithTag("preset_strict").performClick()
        composeRule.waitUntil(30_000) {
            viewModel().settings.value.preset == "strict"
        }
        composeRule.onNodeWithTag("preset_strict").assertIsSelected()
        screenshot("13_settings_strict_light")
        composeRule.onNodeWithTag("settings_close").performClick()

        composeRule.activityRule.scenario.recreate()
        composeRule.waitForIdle()
        openSettings()
        composeRule.onNodeWithTag("preset_strict").assertIsSelected()
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
        waitForImeHidden()
    }

    @Test
    fun case09ImeSendActionSubmitsAndHidesKeyboard() {
        val before = Diagnostics.searchCount
        val state = submitWithIme("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        assertEquals("IME Send must submit one search", before + 1, Diagnostics.searchCount)
        waitForImeHidden()
    }

    @Test
    fun case10FourLineInputGrowsAndStaysAboveKeyboard() {
        composeRule.onNodeWithTag("ask_input").performClick()
        composeRule.onNodeWithTag("ask_input").requestFocus()
        composeRule.onNodeWithTag("ask_input").assertIsFocused()
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
    }

    @Test
    fun case11FontScale13AndDarkModeNoClippedText() {
        // Worst combination: dark mode + font scale 1.3. The screenshot for this
        // state is saved once by K5bUiFontScaleDarkTest.
        UiOverrides.forceDark = true
        UiOverrides.fontScale = 1.3f
        composeRule.activityRule.scenario.recreate()
        composeRule.waitForIdle()
        awaitModelReady()

        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val top = topPassage(state as AskState.Results)
        composeRule.onNodeWithTag("citation_${top.chunkId}").assertIsDisplayed()
        waitForImeHidden()
        assertFullyDisplayedAboveIme("send_button")
    }

    @Test
    fun case12LongEnglishPassageKeepsLtrInsideArabicLayout() {
        val state = submitWithSendButton("What causes bacterial vaginosis?")
        assertTrue("expected Results, got $state", state is AskState.Results)
        val long = (state as AskState.Results).top3.firstOrNull { it.text.length > 350 }
            ?: error("no long passage in the top 3")
        composeRule.waitUntil(60_000) {
            composeRule.onAllNodes(
                hasTagPrefix("passage_body_") and hasTagSuffix("_ltr")
            ).fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("expand_${long.chunkId}")
            .performScrollTo()
            .performClick()
        composeRule.waitForIdle()
        composeRule.onNodeWithTag("expand_${long.chunkId}")
            .performScrollTo()
        screenshot("14_long_english_passage_light")
    }
}
