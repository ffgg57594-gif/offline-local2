package com.medai.assistant.k7a

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTouchInput
import com.medai.assistant.k5b.K5bUiTestBase
import com.medai.assistant.llm.ModelState
import com.medai.assistant.runtime.AppGraph
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertFalse
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File

/**
 * K7a: ui-screenshots-v4 — the "الموديل" settings section in every state
 * and the LLM test screen with streamed output plus stats.
 *
 * All six shots are full device screenshots with real system bars. 02 is a
 * live injected state through the same state flow the real download uses;
 * 03 uses a real verified GGUF file placed through the production storage
 * path; 04 performs a real rejected SAF import (flipped byte); 05/06 drive
 * the real engine end to end.
 */
class K7aModelScreenshotsTest : K5bUiTestBase() {

    private val defaultModelId = "qwen2.5-1.5b-instruct-q4km"
    private val fallbackModelId = "qwen2.5-0.5b-instruct-q4km"

    private fun modelManager() = AppGraph.modelManager(context)

    private fun openSettingsAndScrollToModels() {
        openSettings()
        composeRule.onNodeWithTag("model_section").performScrollTo()
        composeRule.waitForIdle()
    }

    @Test
    fun state01ModelNotInstalled() {
        modelManager().resetForUiTest()
        composeRule.waitUntil(30_000) {
            modelManager().stateOf(defaultModelId) is ModelState.NotInstalled
        }
        openSettingsAndScrollToModels()
        composeRule.onNodeWithTag("model_section").assertIsDisplayed()
        composeRule.onNodeWithTag("model_state_$defaultModelId")
            .performScrollTo()
            .assertIsDisplayed()
        composeRule.waitUntil(10_000) {
            composeRule.onAllNodesWithText("غير مثبت").fetchSemanticsNodes().isNotEmpty()
        }
        screenshotV4("01_settings_model_not_installed")
        composeRule.onNodeWithTag("settings_close").performClick()
    }

    @Test
    fun state02ModelDownloading() {
        modelManager().resetForUiTest()
        composeRule.waitUntil(30_000) {
            modelManager().stateOf(defaultModelId) is ModelState.NotInstalled
        }
        modelManager().injectStateForUiTest(
            defaultModelId,
            ModelState.Downloading(
                modelId = defaultModelId,
                bytesSoFar = 612_000_000L,
                totalBytes = 1_117_320_736L
            )
        )
        openSettingsAndScrollToModels()
        composeRule.onNodeWithTag("model_progress_$defaultModelId")
            .performScrollTo()
            .assertIsDisplayed()
        composeRule.waitUntil(10_000) {
            composeRule
                .onAllNodesWithText("54% (583 من 1065 ميجابايت)")
                .fetchSemanticsNodes()
                .isNotEmpty()
        }
        composeRule.onNodeWithTag("model_cancel_$defaultModelId")
            .performScrollTo()
            .assertIsDisplayed()
        screenshotV4("02_settings_model_downloading")
        composeRule.onNodeWithTag("settings_close").performClick()
        modelManager().injectStateForUiTest(defaultModelId, ModelState.NotInstalled)
    }

    @Test
    fun state03ModelReady() {
        // A real, sha-verified GGUF file placed in the production models
        // directory under the catalog 0.5B slot, then discovered through
        // the real refresh() scan.
        val tiny = K7aTestModels.ensureDownloaded(context)
        val slot = File(context.filesDir, "models/qwen2.5-0.5b-instruct-q4_k_m.gguf")
        slot.parentFile?.mkdirs()
        tiny.copyTo(slot, overwrite = true)
        modelManager().refresh()
        composeRule.waitUntil(30_000) {
            modelManager().stateOf(fallbackModelId) is ModelState.Ready
        }
        openSettingsAndScrollToModels()
        composeRule.onNodeWithTag("model_state_$fallbackModelId")
            .performScrollTo()
            .assertIsDisplayed()
        composeRule.waitUntil(10_000) {
            composeRule.onAllNodesWithText(
                "جاهز — qwen2.5-0.5b-instruct-q4_k_m.gguf (1 ميجابايت على القرص)"
            ).fetchSemanticsNodes().isNotEmpty()
        }
        screenshotV4("03_settings_model_ready")
        composeRule.onNodeWithTag("settings_close").performClick()
    }

    @Test
    fun state04ModelErrorFromRejectedImport() {
        modelManager().resetForUiTest()
        composeRule.waitUntil(30_000) {
            modelManager().stateOf(defaultModelId) is ModelState.NotInstalled
        }
        // Real SAF import path fed a corrupted copy of the tiny model: the
        // sha256 must not match any catalog entry, so the manager must
        // reject it with "الملف غير مطابق للمتوقع".
        val tiny = K7aTestModels.ensureDownloaded(context)
        val corrupted = tiny.readBytes().also { bytes -> bytes[100] = (bytes[100].toInt() xor 0x55).toByte() }
        val accepted = runBlocking {
            modelManager().importFrom { ByteArrayInputStream(corrupted) }
        }
        assertFalse(accepted)
        openSettingsAndScrollToModels()
        composeRule.waitUntil(10_000) {
            composeRule.onAllNodesWithText("الملف غير مطابق للمتوقع")
                .fetchSemanticsNodes()
                .isNotEmpty()
        }
        composeRule.onNodeWithTag("model_error_$defaultModelId")
            .performScrollTo()
            .assertIsDisplayed()
        screenshotV4("04_settings_model_error")
        composeRule.onNodeWithTag("settings_close").performClick()
        modelManager().injectStateForUiTest(defaultModelId, ModelState.NotInstalled)
    }

    @Test
    fun state05And06LlmTestScreenStreamingAndStats() {
        // Make sure a real, verified GGUF exists in the models dir no
        // matter which test order JUnit picks.
        K7aTestModels.ensureDownloaded(context)
        // Enter through the real debug path: long-press on the app title.
        composeRule.onNodeWithTag("app_title").performTouchInput { longClick() }
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithTag("llm_test_entry")
                .fetchSemanticsNodes()
                .isNotEmpty()
        }
        composeRule.onNodeWithTag("llm_test_entry").performScrollTo().performClick()
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithTag("llm_test_model_status")
                .fetchSemanticsNodes()
                .isNotEmpty()
        }
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithTag("llm_test_load").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("llm_test_load").performClick()

        // Real load of the real verified file through the real engine.
        composeRule.waitUntil(120_000) {
            composeRule.onAllNodesWithTag("llm_test_model_info").fetchSemanticsNodes().isNotEmpty() ||
                composeRule.onAllNodesWithTag("llm_test_load_error").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule
            .onAllNodesWithText("فشل التحميل", substring = true)
            .fetchSemanticsNodes()
            .let { errors ->
                check(errors.isEmpty()) { "model load failed on the LLM test screen" }
            }

        // Short prompt only on the emulator (the tiny model has ctx 256).
        composeRule.onNodeWithTag("llm_test_prompt_short").performClick()
        composeRule.onNodeWithTag("llm_test_generate").performClick()

        // 05: streamed output while the generation is still running.
        composeRule.waitUntil(120_000) {
            composeRule.onAllNodesWithTag("llm_test_output").fetchSemanticsNodes().isNotEmpty()
        }
        screenshotV4("05_llm_test_streamed_output")

        // 06: completed run with stats + peak PSS + thermal + copy report.
        composeRule.waitUntil(180_000) {
            composeRule.onAllNodesWithTag("llm_test_stats").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("llm_test_copy_report").performScrollTo()
        screenshotV4("06_llm_test_stats")

        // Sanity: exactly one stats node (the run finished, buttons reset).
        composeRule.onAllNodesWithTag("llm_test_stats").assertCountEquals(1)
    }
}
