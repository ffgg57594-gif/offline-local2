package com.medai.assistant.design

import android.graphics.Bitmap
import androidx.activity.ComponentActivity
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.medai.assistant.design.gallery.DesignGallery
import com.medai.assistant.design.gallery.GallerySection
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.FileOutputStream

/**
 * Instrumented test rendering and capturing Design Gallery screenshots for STAGE UI-A.
 * Renders Direction A (PAPER_INK) and Direction B (CLINICAL_NIGHT), each in:
 * - Light
 * - Dark
 * - Light with Font Scale 1.3
 * Across all 6 component groups (cards, citation + bubbles, refusal + empty, input + progress, sheet, top bar).
 */
@RunWith(AndroidJUnit4::class)
class DesignGalleryTest {

    @get:Rule
    val composeRule = createAndroidComposeRule<ComponentActivity>()

    private fun renderAndCapture(
        name: String,
        direction: DesignDirection,
        darkTheme: Boolean,
        fontScale: Float,
        section: GallerySection
    ) {
        composeRule.setContent {
            val systemDensity = LocalDensity.current
            val density = if (fontScale != 1.0f) {
                Density(systemDensity.density, fontScale)
            } else {
                systemDensity
            }

            CompositionLocalProvider(
                LocalLayoutDirection provides LayoutDirection.Rtl,
                LocalDensity provides density
            ) {
                DesignGallery(
                    direction = direction,
                    darkTheme = darkTheme,
                    initialSection = section
                )
            }
        }

        composeRule.waitForIdle()
        Thread.sleep(400)
        captureScreenshot(name)
    }

    private fun captureScreenshot(name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        val context = instrumentation.targetContext
        val dir = File(context.filesDir, "design-gallery")
        dir.mkdirs()

        val raw: Bitmap = instrumentation.uiAutomation.takeScreenshot()
        val maxWidth = 900
        val bitmap = if (raw.width > maxWidth) {
            val height = (raw.height.toLong() * maxWidth / raw.width).toInt().coerceAtLeast(1)
            Bitmap.createScaledBitmap(raw, maxWidth, height, true)
        } else {
            raw
        }
        try {
            val file = File(dir, "$name.png")
            FileOutputStream(file).use { out ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
            }
        } finally {
            bitmap.recycle()
            if (bitmap !== raw) raw.recycle()
        }
    }

    // =========================================================================
    // Direction A: "ورق وحبر" (Paper & Ink)
    // =========================================================================

    @Test
    fun captureDirectionA_Cards_Light() {
        renderAndCapture("gallery_a_cards_light", DesignDirection.PAPER_INK, false, 1.0f, GallerySection.CARDS)
    }

    @Test
    fun captureDirectionA_Cards_Dark() {
        renderAndCapture("gallery_a_cards_dark", DesignDirection.PAPER_INK, true, 1.0f, GallerySection.CARDS)
    }

    @Test
    fun captureDirectionA_Cards_Font13() {
        renderAndCapture("gallery_a_cards_font13", DesignDirection.PAPER_INK, false, 1.3f, GallerySection.CARDS)
    }

    @Test
    fun captureDirectionA_CitationBubbles_Light() {
        renderAndCapture("gallery_a_citation_bubbles_light", DesignDirection.PAPER_INK, false, 1.0f, GallerySection.CITATION_BUBBLES)
    }

    @Test
    fun captureDirectionA_CitationBubbles_Dark() {
        renderAndCapture("gallery_a_citation_bubbles_dark", DesignDirection.PAPER_INK, true, 1.0f, GallerySection.CITATION_BUBBLES)
    }

    @Test
    fun captureDirectionA_CitationBubbles_Font13() {
        renderAndCapture("gallery_a_citation_bubbles_font13", DesignDirection.PAPER_INK, false, 1.3f, GallerySection.CITATION_BUBBLES)
    }

    @Test
    fun captureDirectionA_RefusalEmpty_Light() {
        renderAndCapture("gallery_a_refusal_empty_light", DesignDirection.PAPER_INK, false, 1.0f, GallerySection.REFUSAL_EMPTY)
    }

    @Test
    fun captureDirectionA_RefusalEmpty_Dark() {
        renderAndCapture("gallery_a_refusal_empty_dark", DesignDirection.PAPER_INK, true, 1.0f, GallerySection.REFUSAL_EMPTY)
    }

    @Test
    fun captureDirectionA_RefusalEmpty_Font13() {
        renderAndCapture("gallery_a_refusal_empty_font13", DesignDirection.PAPER_INK, false, 1.3f, GallerySection.REFUSAL_EMPTY)
    }

    @Test
    fun captureDirectionA_InputProgress_Light() {
        renderAndCapture("gallery_a_input_progress_light", DesignDirection.PAPER_INK, false, 1.0f, GallerySection.INPUT_PROGRESS)
    }

    @Test
    fun captureDirectionA_InputProgress_Dark() {
        renderAndCapture("gallery_a_input_progress_dark", DesignDirection.PAPER_INK, true, 1.0f, GallerySection.INPUT_PROGRESS)
    }

    @Test
    fun captureDirectionA_InputProgress_Font13() {
        renderAndCapture("gallery_a_input_progress_font13", DesignDirection.PAPER_INK, false, 1.3f, GallerySection.INPUT_PROGRESS)
    }

    @Test
    fun captureDirectionA_Sheet_Light() {
        renderAndCapture("gallery_a_sheet_light", DesignDirection.PAPER_INK, false, 1.0f, GallerySection.SHEET)
    }

    @Test
    fun captureDirectionA_Sheet_Dark() {
        renderAndCapture("gallery_a_sheet_dark", DesignDirection.PAPER_INK, true, 1.0f, GallerySection.SHEET)
    }

    @Test
    fun captureDirectionA_Sheet_Font13() {
        renderAndCapture("gallery_a_sheet_font13", DesignDirection.PAPER_INK, false, 1.3f, GallerySection.SHEET)
    }

    @Test
    fun captureDirectionA_TopBar_Light() {
        renderAndCapture("gallery_a_topbar_light", DesignDirection.PAPER_INK, false, 1.0f, GallerySection.TOPBAR_SETTINGS)
    }

    @Test
    fun captureDirectionA_TopBar_Dark() {
        renderAndCapture("gallery_a_topbar_dark", DesignDirection.PAPER_INK, true, 1.0f, GallerySection.TOPBAR_SETTINGS)
    }

    @Test
    fun captureDirectionA_TopBar_Font13() {
        renderAndCapture("gallery_a_topbar_font13", DesignDirection.PAPER_INK, false, 1.3f, GallerySection.TOPBAR_SETTINGS)
    }

    // =========================================================================
    // Direction B: "ليل سريري" (Clinical Night)
    // =========================================================================

    @Test
    fun captureDirectionB_Cards_Light() {
        renderAndCapture("gallery_b_cards_light", DesignDirection.CLINICAL_NIGHT, false, 1.0f, GallerySection.CARDS)
    }

    @Test
    fun captureDirectionB_Cards_Dark() {
        renderAndCapture("gallery_b_cards_dark", DesignDirection.CLINICAL_NIGHT, true, 1.0f, GallerySection.CARDS)
    }

    @Test
    fun captureDirectionB_Cards_Font13() {
        renderAndCapture("gallery_b_cards_font13", DesignDirection.CLINICAL_NIGHT, false, 1.3f, GallerySection.CARDS)
    }

    @Test
    fun captureDirectionB_CitationBubbles_Light() {
        renderAndCapture("gallery_b_citation_bubbles_light", DesignDirection.CLINICAL_NIGHT, false, 1.0f, GallerySection.CITATION_BUBBLES)
    }

    @Test
    fun captureDirectionB_CitationBubbles_Dark() {
        renderAndCapture("gallery_b_citation_bubbles_dark", DesignDirection.CLINICAL_NIGHT, true, 1.0f, GallerySection.CITATION_BUBBLES)
    }

    @Test
    fun captureDirectionB_CitationBubbles_Font13() {
        renderAndCapture("gallery_b_citation_bubbles_font13", DesignDirection.CLINICAL_NIGHT, false, 1.3f, GallerySection.CITATION_BUBBLES)
    }

    @Test
    fun captureDirectionB_RefusalEmpty_Light() {
        renderAndCapture("gallery_b_refusal_empty_light", DesignDirection.CLINICAL_NIGHT, false, 1.0f, GallerySection.REFUSAL_EMPTY)
    }

    @Test
    fun captureDirectionB_RefusalEmpty_Dark() {
        renderAndCapture("gallery_b_refusal_empty_dark", DesignDirection.CLINICAL_NIGHT, true, 1.0f, GallerySection.REFUSAL_EMPTY)
    }

    @Test
    fun captureDirectionB_RefusalEmpty_Font13() {
        renderAndCapture("gallery_b_refusal_empty_font13", DesignDirection.CLINICAL_NIGHT, false, 1.3f, GallerySection.REFUSAL_EMPTY)
    }

    @Test
    fun captureDirectionB_InputProgress_Light() {
        renderAndCapture("gallery_b_input_progress_light", DesignDirection.CLINICAL_NIGHT, false, 1.0f, GallerySection.INPUT_PROGRESS)
    }

    @Test
    fun captureDirectionB_InputProgress_Dark() {
        renderAndCapture("gallery_b_input_progress_dark", DesignDirection.CLINICAL_NIGHT, true, 1.0f, GallerySection.INPUT_PROGRESS)
    }

    @Test
    fun captureDirectionB_InputProgress_Font13() {
        renderAndCapture("gallery_b_input_progress_font13", DesignDirection.CLINICAL_NIGHT, false, 1.3f, GallerySection.INPUT_PROGRESS)
    }

    @Test
    fun captureDirectionB_Sheet_Light() {
        renderAndCapture("gallery_b_sheet_light", DesignDirection.CLINICAL_NIGHT, false, 1.0f, GallerySection.SHEET)
    }

    @Test
    fun captureDirectionB_Sheet_Dark() {
        renderAndCapture("gallery_b_sheet_dark", DesignDirection.CLINICAL_NIGHT, true, 1.0f, GallerySection.SHEET)
    }

    @Test
    fun captureDirectionB_Sheet_Font13() {
        renderAndCapture("gallery_b_sheet_font13", DesignDirection.CLINICAL_NIGHT, false, 1.3f, GallerySection.SHEET)
    }

    @Test
    fun captureDirectionB_TopBar_Light() {
        renderAndCapture("gallery_b_topbar_light", DesignDirection.CLINICAL_NIGHT, false, 1.0f, GallerySection.TOPBAR_SETTINGS)
    }

    @Test
    fun captureDirectionB_TopBar_Dark() {
        renderAndCapture("gallery_b_topbar_dark", DesignDirection.CLINICAL_NIGHT, true, 1.0f, GallerySection.TOPBAR_SETTINGS)
    }

    @Test
    fun captureDirectionB_TopBar_Font13() {
        renderAndCapture("gallery_b_topbar_font13", DesignDirection.CLINICAL_NIGHT, false, 1.3f, GallerySection.TOPBAR_SETTINGS)
    }
}
