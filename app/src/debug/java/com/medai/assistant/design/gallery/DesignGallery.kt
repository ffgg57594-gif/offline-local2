package com.medai.assistant.design.gallery

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import com.medai.assistant.design.DesignDirection
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.MedAiDesignTheme
import com.medai.assistant.design.components.AssetInstallProgress
import com.medai.assistant.design.components.CitationLine
import com.medai.assistant.design.components.EmptyState
import com.medai.assistant.design.components.InputBar
import com.medai.assistant.design.components.MedAiTopBar
import com.medai.assistant.design.components.PassageCard
import com.medai.assistant.design.components.QuestionBubble
import com.medai.assistant.design.components.RefusalCard
import com.medai.assistant.design.components.SearchingInlineProgress
import com.medai.assistant.design.components.SheetScaffold
import com.medai.assistant.design.components.ShimmerResultCardSkeleton

/**
 * Gallery sections corresponding to the required component groups in STAGE UI-A item 6:
 * - CARDS: Cards group (including standard passage and deliberately long English passage)
 * - CITATION_BUBBLES: CitationLine and QuestionBubble group
 * - REFUSAL_EMPTY: RefusalCard and EmptyState group
 * - INPUT_PROGRESS: InputBar and Progress states (determinate, inline searching, shimmer)
 * - SHEET: SheetScaffold group
 * - TOPBAR_SETTINGS: TopBar and controls group
 */
enum class GallerySection(val labelArabic: String) {
    CARDS("البطاقات"),
    CITATION_BUBBLES("المصادر والفقاعات"),
    REFUSAL_EMPTY("الرفض والحالة الفارغة"),
    INPUT_PROGRESS("الإدخال والتحميل"),
    SHEET("النافذة المرجعية"),
    TOPBAR_SETTINGS("الشريط العلوي"),
    ALL("الكل")
}

/**
 * Real medical chunks from books_knowledge.db (Obstetrics and Gynecology Textbook).
 */
object RealMedicalContent {
    const val BOOK_TITLE = "Obstetrics and Gynecology Textbook"

    // Real Chunk 217 (page 70)
    const val CHUNK_CYSTITIS =
        "Symptoms of acute cystitis followed by systemic manifestations as nausea and vomiting " +
        "in association with rigors, chills, and loin pain. Signs: high fever, tachycardia, " +
        "and tender loin (right is more common due to dextro-rotation of the uterus with more pressure " +
        "on the right ureter). Significance: if not early detected and adequately managed acute " +
        "pyelonephritis may lead to serious maternal and fetal complications as sepsis, anemia, " +
        "PROM and PTL. Laboratory Diagnosis: positive urine culture showing > 100,000 CFU."

    // Real Chunk 6 (page 8) - deliberately long English passage (1133 characters)
    const val CHUNK_PLACENTA_LONG =
        "ANATOMY AND HISTOLOGY: The placenta represents the interface between the mother and the fetus. " +
        "It is formed from the chorion frondosum and the decidua basalis. Morphology: the placenta is " +
        "discoid in shape, about 20 cm in diameter, 1 inch in thickness at the center, 0.5 inch at the " +
        "periphery and about 500 gm in weight. It has 2 surfaces: 1. Fetal surface: Smooth, glistening " +
        "and is covered by amnion which is reflected on the umbilical cord which is inserted at or near " +
        "the center of this surface. 2. Maternal surface: Dull greyish red in color, divided into 10-38 " +
        "lobules (called cotyledons). Attachment: the placenta is normally attached to the upper uterine " +
        "segment, 60% in the posterior wall, and 40% in the anterior wall. PLACENTAL PHYSIOLOGY: The human " +
        "placenta has three main functions, namely transfer of nutrients, production of a group of hormones " +
        "and enzymes (endocrine and metabolic function), and an immunological role. Transfer function can " +
        "occur through many mechanisms: Simple diffusion, Facilitated diffusion, Active transport or Pinocytosis."
}

/**
 * DesignGallery composable for STAGE UI-A:
 * Debug-only gallery rendering every component with realistic medical content,
 * RTL Arabic shell, and Source Serif 4 English passages.
 */
@Composable
fun DesignGallery(
    direction: DesignDirection = DesignDirection.PAPER_INK,
    darkTheme: Boolean = false,
    initialSection: GallerySection = GallerySection.ALL,
    modifier: Modifier = Modifier
) {
    MedAiDesignTheme(direction = direction, darkTheme = darkTheme) {
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
            var selectedSection by remember { mutableStateOf(initialSection) }
            val scrollState = rememberScrollState()

            Column(
                modifier = modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background)
                    .testTag("design_gallery_root")
            ) {
                // If rendering ALL in interactive debug mode, show a tab row to switch sections
                if (initialSection == GallerySection.ALL) {
                    var selectedTabIndex by remember { mutableIntStateOf(0) }
                    ScrollableTabRow(
                        selectedTabIndex = selectedTabIndex,
                        containerColor = MaterialTheme.colorScheme.surface,
                        contentColor = MaterialTheme.colorScheme.primary,
                        edgePadding = DesignSpacing.space16
                    ) {
                        GallerySection.values().forEachIndexed { index, section ->
                            Tab(
                                selected = selectedTabIndex == index,
                                onClick = {
                                    selectedTabIndex = index
                                    selectedSection = section
                                },
                                text = {
                                    Text(
                                        text = section.labelArabic,
                                        fontFamily = DesignFonts.ArabicUiFamily,
                                        fontWeight = FontWeight.Medium
                                    )
                                }
                            )
                        }
                    }
                }

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(scrollState)
                        .padding(DesignSpacing.space16),
                    verticalArrangement = Arrangement.spacedBy(DesignSpacing.space16)
                ) {
                    when (selectedSection) {
                        GallerySection.CARDS -> CardsGroupContent()
                        GallerySection.CITATION_BUBBLES -> CitationBubblesGroupContent()
                        GallerySection.REFUSAL_EMPTY -> RefusalEmptyGroupContent()
                        GallerySection.INPUT_PROGRESS -> InputProgressGroupContent()
                        GallerySection.SHEET -> SheetGroupContent()
                        GallerySection.TOPBAR_SETTINGS -> TopBarSettingsGroupContent()
                        GallerySection.ALL -> {
                            CardsGroupContent()
                            CitationBubblesGroupContent()
                            RefusalEmptyGroupContent()
                            InputProgressGroupContent()
                            SheetGroupContent()
                            TopBarSettingsGroupContent()
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun CardsGroupContent() {
    Column(
        verticalArrangement = Arrangement.spacedBy(DesignSpacing.space16),
        modifier = Modifier.testTag("group_cards")
    ) {
        Text(
            text = "بطاقات المقاطع المرجعية (Passage Cards)",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
            fontFamily = DesignFonts.ArabicUiFamily
        )

        // Card 1: Standard passage
        PassageCard(
            passageText = RealMedicalContent.CHUNK_CYSTITIS,
            bookTitle = RealMedicalContent.BOOK_TITLE,
            page = 70,
            rank = 1,
            highlightWords = listOf("acute", "cystitis", "pyelonephritis", "signs"),
            onCitationClick = {},
            onCopy = {}
        )

        // Card 2: Deliberately long English passage inside the Arabic layout
        PassageCard(
            passageText = RealMedicalContent.CHUNK_PLACENTA_LONG,
            bookTitle = RealMedicalContent.BOOK_TITLE,
            page = 8,
            rank = 2,
            highlightWords = listOf("placenta", "interface", "fetus", "physiology", "diffusion"),
            initiallyExpanded = true,
            onCitationClick = {},
            onCopy = {}
        )
    }
}

@Composable
fun CitationBubblesGroupContent() {
    Column(
        verticalArrangement = Arrangement.spacedBy(DesignSpacing.space16),
        modifier = Modifier.testTag("group_citation_bubbles")
    ) {
        Text(
            text = "المصادر وفقاعات الأسئلة (Citation & Bubbles)",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
            fontFamily = DesignFonts.ArabicUiFamily
        )

        // English question bubble (direction detected as LTR, aligned to start side in RTL shell)
        QuestionBubble(
            question = "What causes acute cystitis in pregnancy?",
            testTag = "bubble_english"
        )

        // Arabic question bubble (direction detected as RTL, aligned to start side)
        QuestionBubble(
            question = "ما هي علامات وأعراض التهاب المثانة الحاد أثناء الحمل؟",
            testTag = "bubble_arabic"
        )

        // Explicit bidi CitationLine
        CitationLine(
            bookTitle = RealMedicalContent.BOOK_TITLE,
            page = 261,
            testTag = "citation_standalone_261"
        )

        CitationLine(
            bookTitle = RealMedicalContent.BOOK_TITLE,
            page = 70,
            testTag = "citation_standalone_70"
        )
    }
}

@Composable
fun RefusalEmptyGroupContent() {
    Column(
        verticalArrangement = Arrangement.spacedBy(DesignSpacing.space16),
        modifier = Modifier.testTag("group_refusal_empty")
    ) {
        Text(
            text = "بطاقة الرفض والحالة الفارغة (Refusal & Empty State)",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
            fontFamily = DesignFonts.ArabicUiFamily
        )

        // RefusalCard with exact required sentence
        RefusalCard(
            onShowNearestClick = {}
        )

        // EmptyState with Canvas line-art book + magnifier and 4 example cards
        EmptyState()
    }
}

@Composable
fun InputProgressGroupContent() {
    var queryText by remember { mutableStateOf("What are the potential complications of IUD?") }

    Column(
        verticalArrangement = Arrangement.spacedBy(DesignSpacing.space16),
        modifier = Modifier.testTag("group_input_progress")
    ) {
        Text(
            text = "حقل الإدخال وحالات التحميل (Input & Progress States)",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
            fontFamily = DesignFonts.ArabicUiFamily
        )

        // InputBar with text
        InputBar(
            value = queryText,
            onValueChange = { queryText = it },
            onSubmit = {}
        )

        // Disabled InputBar
        InputBar(
            value = "",
            onValueChange = {},
            onSubmit = {},
            enabled = false,
            placeholder = "جاري تهيئة المرجع الطبي..."
        )

        // Searching inline spinner
        SearchingInlineProgress()

        // Determinate installation progress bar
        AssetInstallProgress(
            fileName = "books_knowledge.db",
            doneBytes = 4194304,
            totalBytes = 6291456
        )

        // Shimmer result card placeholder
        ShimmerResultCardSkeleton()
    }
}

@Composable
fun SheetGroupContent() {
    Column(
        verticalArrangement = Arrangement.spacedBy(DesignSpacing.space16),
        modifier = Modifier.testTag("group_sheet")
    ) {
        Text(
            text = "النافذة المرجعية المنبثقة (Sheet Scaffold)",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
            fontFamily = DesignFonts.ArabicUiFamily
        )

        SheetScaffold(
            title = "المقطع الطبي الكامل",
            bookTitle = RealMedicalContent.BOOK_TITLE,
            page = 8,
            bodyText = RealMedicalContent.CHUNK_PLACENTA_LONG,
            onClose = {},
            hasPrevious = true,
            hasNext = true,
            onPrevious = {},
            onNext = {}
        )
    }
}

@Composable
fun TopBarSettingsGroupContent() {
    Column(
        verticalArrangement = Arrangement.spacedBy(DesignSpacing.space16),
        modifier = Modifier.testTag("group_topbar_settings")
    ) {
        Text(
            text = "الشريط العلوي وعناصر الضبط (TopBar & Settings)",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
            fontFamily = DesignFonts.ArabicUiFamily
        )

        MedAiTopBar(
            onSettingsClick = {}
        )
    }
}
