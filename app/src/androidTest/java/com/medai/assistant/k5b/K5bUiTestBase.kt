package com.medai.assistant.k5b

import android.content.Context
import android.os.ParcelFileDescriptor
import android.view.inputmethod.InputMethodManager
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performImeAction
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.requestFocus
import androidx.compose.ui.test.swipeUp
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.ViewModelProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.medai.assistant.MainActivity
import com.medai.assistant.ask.AskState
import com.medai.assistant.ask.AskViewModel
import com.medai.assistant.runtime.AppGraph
import com.medai.assistant.runtime.AppRuntimeState
import com.medai.assistant.settings.SettingsRepository
import com.medai.assistant.settings.settingsDataStore
import com.medai.assistant.ui.UiOverrides
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule

abstract class K5bUiTestBase {

    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    open val forceDark: Boolean = false
    open val fontScale: Float = 1f

    protected val context: Context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Before
    fun applyUiOverridesAndWaitForModel() {
        UiOverrides.forceDark = forceDark
        UiOverrides.fontScale = fontScale
        composeRule.activityRule.scenario.recreate()
        composeRule.waitForIdle()
        awaitModelReady()
        resetToBalanced()
        ensureScreenAwakeAndFocused()
    }

    @After
    fun clearUiOverrides() {
        UiOverrides.forceDark = null
        UiOverrides.fontScale = null
        UiOverrides.searchDelayMs = 0L
    }

    protected fun viewModel(): AskViewModel =
        ViewModelProvider(composeRule.activity)[AskViewModel::class.java]

    protected fun awaitModelReady() {
        val deadline = System.currentTimeMillis() + 600_000
        while (System.currentTimeMillis() < deadline) {
            val runtime = AppGraph.runtimeState.value
            if (runtime is AppRuntimeState.Ready) {
                composeRule.waitUntil(120_000) {
                    viewModel().state.value is AskState.Ready
                }
                return
            }
            if (runtime is AppRuntimeState.Failed) {
                throw AssertionError("AppGraph failed: ${runtime.message}")
            }
            Thread.sleep(250)
        }
        throw AssertionError("AppGraph did not become Ready within 600s")
    }

    private fun resetToBalanced() {
        val repository = SettingsRepository(composeRule.activity.settingsDataStore)
        runBlocking {
            repository.setPreset("balanced")
            // K5c: diagnostics mode must not leak between test classes; some
            // cases toggle it and the next class could otherwise show cosine.
            repository.setShowTimings(false)
        }
        Thread.sleep(250)
        composeRule.waitUntil(30_000) {
            viewModel().settings.value.preset == "balanced" &&
                !viewModel().settings.value.showTimings
        }
    }

    /**
     * A sleeping display (Pixel profile default) leaves the activity resumed
     * but without window focus, so InputMethodManager refuses to show the IME
     * with "view is not served". Wake the device and wait for real focus.
     */
    private fun ensureScreenAwakeAndFocused() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        fun shell(command: String) {
            instrumentation.uiAutomation.executeShellCommand(command).close()
        }
        val deadline = System.currentTimeMillis() + 30_000
        while (System.currentTimeMillis() < deadline) {
            var focused = false
            composeRule.activityRule.scenario.onActivity { activity ->
                focused = activity.window.decorView.hasWindowFocus()
            }
            if (focused) return
            shell("input keyevent KEYCODE_WAKEUP")
            shell("wm dismiss-keyguard")
            Thread.sleep(500)
        }
        throw AssertionError("the activity window never gained focus; the IME cannot be shown")
    }

    protected fun waitForUiText(text: String, timeoutMs: Long = 180_000) {
        composeRule.waitUntil(timeoutMs) {
            composeRule.onAllNodesWithText(text, substring = false)
                .fetchSemanticsNodes().isNotEmpty()
        }
    }

    protected fun submitWithSendButton(question: String): AskState {
        composeRule.onNodeWithTag("ask_input").performClick()
        composeRule.onNodeWithTag("ask_input").performTextClearance()
        composeRule.onNodeWithTag("ask_input").performTextInput(question)
        composeRule.onNodeWithTag("send_button").performClick()
        return awaitTerminalState()
    }

    protected fun submitWithIme(question: String): AskState {
        composeRule.onNodeWithTag("ask_input").performClick()
        composeRule.onNodeWithTag("ask_input").performTextClearance()
        composeRule.onNodeWithTag("ask_input").performTextInput(question)
        composeRule.onNodeWithTag("ask_input").performImeAction()
        return awaitTerminalState()
    }

    protected fun awaitTerminalState(timeoutMs: Long = 240_000): AskState {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val state = viewModel().state.value
            if (state is AskState.Results || state is AskState.Rejected || state is AskState.Error) {
                composeRule.waitForIdle()
                Thread.sleep(300)
                composeRule.waitForIdle()
                return state
            }
            Thread.sleep(100)
        }
        throw AssertionError("search did not finish within ${timeoutMs}ms")
    }

    /**
     * The results screen re-issues bringIntoView at 350 ms and 850 ms after the
     * answer arrives (it survives the IME hide animation). Let those settle
     * before scrolling to a lower card, otherwise the automatic scroll and the
     * test scroll can race and the citation tap lands on the wrong card.
     */
    protected fun waitForResultsScrollToSettle() {
        Thread.sleep(1_100)
        composeRule.waitForIdle()
    }

    /**
     * Scrolls a citation chip into view and opens the passage sheet. A real
     * touch tap is tried first; on the headless emulator the results list
     * re-issues bringIntoView after the IME hides, which can move the chip
     * between the scroll and the tap, so fall back to the chip's accessibility
     * OnClick action instead of hanging for 30 s on a missed tap.
     */
    protected fun openCitationSheet(chunkId: Any) {
        val citation = composeRule.onNodeWithTag("citation_$chunkId").performScrollTo()
        citation.performClick()
        val shown = runCatching {
            composeRule.waitUntil(10_000) {
                composeRule.onAllNodesWithText("المقطع الكامل").fetchSemanticsNodes().isNotEmpty()
            }
        }.isSuccess
        if (!shown) {
            citation.performSemanticsAction(SemanticsActions.OnClick)
        }
    }

    protected fun openSettings() {
        composeRule.onNodeWithTag("settings_button").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodes(hasTagPrefix("preset_")).fetchSemanticsNodes().isNotEmpty()
        }
    }

    protected fun screenshot(name: String) {
        composeRule.waitForIdle()
        awaitNoSystemErrorDialog(name)
        K5bArtifacts.screenshot(context, name)
    }

    /**
     * Refuses to save a PNG that shows a system "isn't responding" dialog. If
     * one is up, close it and fail with the window title instead of shipping a
     * polluted screenshot as visual evidence.
     */
    private fun awaitNoSystemErrorDialog(name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        fun focusedWindow(): String {
            val pfd = instrumentation.uiAutomation
                .executeShellCommand("dumpsys window | grep -m2 mCurrentFocus")
            return ParcelFileDescriptor.AutoCloseInputStream(pfd)
                .bufferedReader().use { it.readText() }.trim()
        }
        fun isError(focus: String): Boolean =
            focus.contains("Application Not Responding", ignoreCase = true) ||
                focus.contains("Application Error", ignoreCase = true) ||
                focus.contains("ErrorDialog", ignoreCase = true)

        val deadline = System.currentTimeMillis() + 10_000
        var focus = focusedWindow()
        while (System.currentTimeMillis() < deadline) {
            if (!isError(focus)) return
            instrumentation.uiAutomation.executeShellCommand(
                "am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS"
            ).close()
            Thread.sleep(500)
            focus = focusedWindow()
        }
        throw AssertionError("screenshot $name blocked by a system dialog: $focus")
    }

    protected fun hasTagPrefix(prefix: String): SemanticsMatcher =
        SemanticsMatcher("test tag starts with $prefix") { node ->
            node.config.getOrNull(SemanticsProperties.TestTag)?.startsWith(prefix) == true
        }

    protected fun hasTagSuffix(suffix: String): SemanticsMatcher =
        SemanticsMatcher("test tag ends with $suffix") { node ->
            node.config.getOrNull(SemanticsProperties.TestTag)?.endsWith(suffix) == true
        }

    protected fun assertTagCount(prefix: String, expected: Int) {
        composeRule.onAllNodes(hasTagPrefix(prefix)).assertCountEquals(expected)
    }

    /**
     * Asserts the node is inside the Compose root and, when the IME is open,
     * that its bottom edge is above the keyboard inset.
     */
    protected fun assertFullyDisplayedAboveIme(tag: String) {
        composeRule.onNodeWithTag(tag).assertIsDisplayed()
        val bounds = composeRule.onNodeWithTag(tag).fetchSemanticsNode().boundsInRoot
        assertTrue("node $tag has zero size", bounds.width > 0f && bounds.height > 0f)
        assertTrue(
            "node $tag starts outside the visible root: $bounds",
            bounds.left >= -1f && bounds.top >= -1f
        )
        val imeBottom = imeBottomPx()
        if (imeVisible() && imeBottom > 0) {
            val visibleFloor = rootHeightPx() - imeBottom
            assertTrue(
                "node $tag bottom ${bounds.bottom} is under the keyboard " +
                    "(visible floor $visibleFloor)",
                bounds.bottom <= visibleFloor + 2f
            )
        }
    }

    protected fun imeVisible(): Boolean {
        var visible = false
        composeRule.activityRule.scenario.onActivity { activity ->
            val insets = ViewCompat.getRootWindowInsets(activity.window.decorView)
            visible = insets?.isVisible(WindowInsetsCompat.Type.ime()) == true
        }
        return visible
    }

    protected fun imeBottomPx(): Int {
        var bottom = 0
        composeRule.activityRule.scenario.onActivity { activity ->
            val insets = ViewCompat.getRootWindowInsets(activity.window.decorView)
            bottom = insets?.getInsets(WindowInsetsCompat.Type.ime())?.bottom ?: 0
        }
        return bottom
    }

    protected fun rootHeightPx(): Float {
        return composeRule.onRoot().fetchSemanticsNode().size.height.toFloat()
    }

    /** Waits until the soft keyboard inset is gone (after Send / chip tap). */
    protected fun waitForImeHidden(timeoutMs: Long = 20_000) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline && imeVisible()) {
            Thread.sleep(100)
        }
        assertTrue("the soft keyboard must be hidden after Send", !imeVisible())
    }

    /** Asserts that a node is fully inside the scrolling area above the input. */
    protected fun assertFullyVisibleAboveInput(tag: String) {
        composeRule.onNodeWithTag(tag).assertIsDisplayed()
        val bounds = composeRule.onNodeWithTag(tag).fetchSemanticsNode().boundsInRoot
        val inputTop = composeRule.onNodeWithTag("ask_input")
            .fetchSemanticsNode().boundsInRoot.top
        assertTrue(
            "node $tag starts outside the visible area: $bounds",
            bounds.top >= -1f && bounds.left >= -1f
        )
        assertTrue(
            "node $tag bottom ${bounds.bottom} is below the input bar top $inputTop",
            bounds.bottom <= inputTop + 2f
        )
    }

    protected fun scrollSheetToBottom() {
        repeat(8) {
            composeRule.onNodeWithTag("sheet_body").performTouchInput {
                swipeUp(durationMillis = 250)
            }
            composeRule.waitForIdle()
        }
    }

    protected fun showKeyboard() {
        composeRule.waitForIdle()
        ensureScreenAwakeAndFocused()
        composeRule.activityRule.scenario.onActivity { activity ->
            val imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
            activity.window.decorView.requestFocus()
            val target = activity.currentFocus ?: activity.window.decorView
            target.requestFocus()
            imm.showSoftInput(target, InputMethodManager.SHOW_IMPLICIT)
            imm.showSoftInput(target, InputMethodManager.SHOW_FORCED)
        }
        var deadline = System.currentTimeMillis() + 20_000
        while (System.currentTimeMillis() < deadline && !imeVisible()) {
            Thread.sleep(200)
        }
        if (!imeVisible()) {
            // A focused Compose field normally opens the IME on tap; retry once
            // after the composition has settled.
            composeRule.onNodeWithTag("ask_input").performClick()
            composeRule.onNodeWithTag("ask_input").requestFocus()
            composeRule.waitForIdle()
            composeRule.activityRule.scenario.onActivity { activity ->
                val imm =
                    activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
                imm.showSoftInput(
                    activity.currentFocus ?: activity.window.decorView,
                    InputMethodManager.SHOW_FORCED
                )
            }
            deadline = System.currentTimeMillis() + 20_000
            while (System.currentTimeMillis() < deadline && !imeVisible()) {
                Thread.sleep(200)
            }
        }
    }
}
