package com.medai.assistant.k5b

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTouchInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * K5b-B: the debug benchmark screen reports every pipeline stage with
 * p50/p95/max, and writes `benchmark.csv` for the CI report.
 */
@RunWith(AndroidJUnit4::class)
class K5bBenchmarkUiTest : K5bUiTestBase() {

    @Test
    fun benchmarkShowsEveryStageAndWritesCsv() {
        composeRule.onNodeWithText("المساعد الطبي").performTouchInput { longClick() }
        composeRule.waitUntil(30_000) {
            composeRule.onAllNodesWithText("Benchmark").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("Run benchmark").performScrollTo().performClick()
        composeRule.waitUntil(180_000) {
            composeRule.onAllNodesWithText("Complete (", substring = true)
                .fetchSemanticsNodes().isNotEmpty()
        }

        listOf("tokenize", "embed", "search", "gate_signals", "gate_decision", "total")
            .forEach { stage ->
                composeRule.onNodeWithTag("benchmark_stage_$stage")
                    .performScrollTo()
                    .assertIsDisplayed()
            }
        screenshot("benchmark_stages_light")

        val csv = File(K5bArtifacts.reportsDir(context), "benchmark.csv")
        assertTrue("benchmark.csv must exist", csv.exists())
        val lines = csv.readLines().filter { it.isNotBlank() }
        assertEquals("header + 5 stages + total + warmup", 8, lines.size)
        assertTrue("benchmark.csv must include tokenize", lines.any { it.startsWith("tokenize,") })
        assertTrue("benchmark.csv must include total", lines.any { it.startsWith("total,") })
    }
}
