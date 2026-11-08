package com.medai.assistant.k5b

import android.content.Context
import android.view.inputmethod.InputMethodManager
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
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.requestFocus
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
    }

    @After
    fun clearUiOverrides() {
        UiOverrides.forceDark = null
        UiOverrides.fontScale = null
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
        runBlocking { repository.setPreset("balanced") }
        Thread.sleep(250)
        composeRule.waitUntil(30_000) {
            viewModel().settings.value.preset == "balanced"
        }
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

    protected fun openSettings() {
        composeRule.onNodeWithTag("settings_button").performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodes(hasTagPrefix("preset_")).fetchSemanticsNodes().isNotEmpty()
        }
    }

    protected fun screenshot(name: String) {
        composeRule.waitForIdle()
        K5bArtifacts.screenshot(context, name)
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

    protected fun showKeyboard() {
        composeRule.waitForIdle()
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
