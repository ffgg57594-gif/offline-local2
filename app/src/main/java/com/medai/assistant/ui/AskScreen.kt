package com.medai.assistant.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.medai.assistant.BookTitles
import com.medai.assistant.R
import com.medai.assistant.ask.AskState
import com.medai.assistant.ask.AskTiming
import com.medai.assistant.ask.AskViewModel
import com.medai.assistant.ask.Passage
import com.medai.assistant.ask.PassageText
import com.medai.assistant.data.BookInfo
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens
import com.medai.assistant.design.components.BookMagnifierIllustration
import com.medai.assistant.design.components.CitationLine
import com.medai.assistant.design.components.InputBar
import com.medai.assistant.design.components.MedAiTopBar
import com.medai.assistant.design.components.QuestionBubble
import com.medai.assistant.design.motion.StaggeredCardEnter
import com.medai.assistant.diagnostics.Diagnostics
import com.medai.assistant.runtime.AppGraph
import com.medai.assistant.settings.AppSettings
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Locale

/** Four real golden questions used by the empty state (golden ids 44, 41, 42, 43). */
val EXAMPLE_QUESTIONS = listOf(
    "What causes bacterial vaginosis?",
    "When is the best time to insert an IUD?",
    "What are the potential complications of IUD use?",
    "What options are available for emergency contraception?"
)

private val EXAMPLE_ICONS = listOf(
    Icons.Filled.Search,
    Icons.Filled.DateRange,
    Icons.Filled.Warning,
    Icons.Filled.FavoriteBorder
)

@OptIn(
    ExperimentalMaterial3Api::class,
    ExperimentalComposeUiApi::class,
    ExperimentalFoundationApi::class
)
@Composable
fun AskScreen(
    viewModel: AskViewModel,
    onOpenDebug: () -> Unit
) {
    val state by viewModel.state.collectAsState()
    val settings by viewModel.settings.collectAsState()

    var input by rememberSaveable { mutableStateOf("") }
    var showSettings by rememberSaveable { mutableStateOf(false) }
    var sheetPassage by remember { mutableStateOf<Passage?>(null) }
    var expandedRefusalQuestion by rememberSaveable { mutableStateOf<String?>(null) }
    var bookInfo by remember { mutableStateOf<BookInfo?>(null) }

    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val clipboard = LocalClipboardManager.current
    val appContext = LocalContext.current.applicationContext
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    val scrollState = rememberScrollState()
    val firstCardRequester = remember { BringIntoViewRequester() }

    // K7a: in-app LLM model download/import wiring for the settings sheet.
    val modelManager = AppGraph.modelManager(appContext)
    val modelStates by modelManager.states.collectAsState()
    val catalogModels = remember { modelManager.models() }
    val modelImportLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            scope.launch {
                // Accepts only a file whose sha256 equals a catalog entry;
                // anything else becomes the "الملف غير مطابق للمتوقع" error state.
                modelManager.importFrom {
                    appContext.contentResolver.openInputStream(uri)
                        ?: error("تعذر فتح الملف المحدد")
                }
            }
        }
    }

    val copy: (String) -> Unit = { text ->
        clipboard.setText(AnnotatedString(text))
        scope.launch { snackbar.showSnackbar("تم النسخ") }
    }
    val dismissKeyboard: () -> Unit = {
        focusManager.clearFocus(force = true)
        keyboard?.hide()
    }
    val submit: () -> Unit = {
        val question = input.trim()
        if (question.isNotEmpty()) {
            dismissKeyboard()
            viewModel.ask(question)
        }
    }
    val canSubmit = state !is AskState.Installing && state !is AskState.LoadingModel

    LaunchedEffect(state) {
        if (state is AskState.Ready && bookInfo == null) {
            bookInfo = viewModel.bookInfo()
        }
    }

    val resultQuestion = when (val current = state) {
        is AskState.Results -> current.question
        is AskState.Rejected ->
            if (expandedRefusalQuestion == current.question) current.question else null
        else -> null
    }
    LaunchedEffect(resultQuestion) {
        if (resultQuestion != null) {
            runCatching { scrollState.animateScrollTo(0) }
            delay(350)
            runCatching { firstCardRequester.bringIntoView() }
            delay(500)
            runCatching { firstCardRequester.bringIntoView() }
        }
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            MedAiTopBar(
                onSettingsClick = { showSettings = true },
                onLongPressDebug = onOpenDebug
            )
        },
        bottomBar = {
            InputBar(
                value = input,
                onValueChange = { input = it },
                onSubmit = submit,
                enabled = canSubmit,
                inputTestTag = "ask_input",
                modifier = Modifier
                    .windowInsetsPadding(WindowInsets.navigationBars.union(WindowInsets.ime))
            )
        },
        snackbarHost = { SnackbarHost(snackbar) }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(scrollState)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            when (val current = state) {
                is AskState.Installing -> InstallingCard(current)
                is AskState.LoadingModel -> LoadingModelCard()
                is AskState.Ready -> EmptyState(
                    bookInfo = bookInfo,
                    onExample = { question ->
                        dismissKeyboard()
                        input = question
                    }
                )
                is AskState.Searching -> {
                    QuestionBubble(current.question)
                    SearchingCard(current.question, viewModel::cancel)
                }
                is AskState.Results -> {
                    QuestionBubble(current.question)
                    if (settings.showTimings) TimingLine(current.timings)
                    ResultList(
                        passages = current.top3,
                        showDiagnostics = settings.showTimings,
                        firstCardRequester = firstCardRequester,
                        onCitationClick = { sheetPassage = it },
                        onCopy = copy
                    )
                }
                is AskState.Rejected -> {
                    QuestionBubble(current.question)
                    if (settings.showTimings) TimingLine(current.timings)
                    val expanded = expandedRefusalQuestion == current.question
                    RefusalCardView(
                        refusal = current.refusal,
                        onShowNearest = if (!expanded) {
                            { expandedRefusalQuestion = current.question }
                        } else null
                    )
                    if (expanded) {
                        TextButton(
                            onClick = { expandedRefusalQuestion = null },
                            modifier = Modifier.heightIn(min = 48.dp)
                        ) {
                            Text(
                                "إخفاء أقرب النتائج",
                                fontFamily = DesignFonts.ArabicUiFamily,
                                fontWeight = FontWeight.Bold
                            )
                        }
                        ResultList(
                            passages = current.top3,
                            showDiagnostics = settings.showTimings,
                            firstCardRequester = firstCardRequester,
                            onCitationClick = { sheetPassage = it },
                            onCopy = copy
                        )
                    }
                }
                is AskState.Error -> ErrorCard(
                    message = current.message,
                    onRetry = submit
                )
            }
        }
    }

    if (showSettings) {
        SettingsSheet(
            settings = settings,
            modelStates = modelStates,
            catalogModels = catalogModels,
            onDownload = { model -> modelManager.download(model) },
            onCancelDownload = { id -> modelManager.cancelDownload(id) },
            onDeleteModel = { id -> modelManager.delete(id) },
            onImportModel = { modelImportLauncher.launch(arrayOf("*/*")) },
            onPreset = viewModel::setPreset,
            onShowTimings = viewModel::setShowTimings,
            onCopyReport = {
                copy(Diagnostics.buildReport(appContext))
            },
            onDismiss = { showSettings = false }
        )
    }

    sheetPassage?.let { passage ->
        PassageSheet(
            initial = passage,
            onDismiss = { sheetPassage = null },
            onNeighbour = viewModel::neighbour,
            onCopy = copy
        )
    }
}

@Composable
private fun InstallingCard(state: AskState.Installing) {
    val fraction = if (state.totalBytes > 0) {
        (state.doneBytes.toFloat() / state.totalBytes.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val percentage = (fraction * 100).toInt()
    val extendedTokens = LocalExtendedDesignTokens.current

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("installing_state"),
        shape = RoundedCornerShape(extendedTokens.cardRadius),
        color = MaterialTheme.colorScheme.surfaceVariant,
        border = BorderStroke(1.dp, extendedTokens.hairlineBorderColor)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                "تجهيز التطبيق",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                "يتم نسخ الملفات الكبيرة مرة واحدة فقط.",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            LinearProgressIndicator(
                progress = { fraction },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp)),
                color = MaterialTheme.colorScheme.primary,
                trackColor = extendedTokens.hairlineBorderColor
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    "${state.fileName} — $percentage%",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    "${state.doneBytes} / ${state.totalBytes} بايت",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun LoadingModelCard() {
    val extendedTokens = LocalExtendedDesignTokens.current
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("loading_model_state"),
        shape = RoundedCornerShape(extendedTokens.cardRadius),
        color = MaterialTheme.colorScheme.surfaceVariant,
        border = BorderStroke(1.dp, extendedTokens.hairlineBorderColor)
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            CircularProgressIndicator(
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(28.dp),
                strokeWidth = 3.dp
            )
            Text(
                "جارٍ تحميل النموذج…",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                "يتم التحميل في الخلفية، ويمكنك كتابة سؤالك الآن.",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
private fun EmptyState(bookInfo: BookInfo?, onExample: (String) -> Unit) {
    val extendedTokens = LocalExtendedDesignTokens.current
    Column(
        verticalArrangement = Arrangement.spacedBy(16.dp),
        modifier = Modifier.testTag("empty_state_container")
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 8.dp),
            contentAlignment = Alignment.Center
        ) {
            BookMagnifierIllustration(
                color = MaterialTheme.colorScheme.primary
            )
        }

        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                "اسأل عن كتابك الطبي",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
                fontFamily = DesignFonts.ArabicUiFamily
            )
            Text(
                "الإجابات من الكتاب المدمج فقط، دون اتصال بالإنترنت.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontFamily = DesignFonts.ArabicUiFamily
            )
            bookInfo?.let { info ->
                Text(
                    "الكتاب المدمج: ${BookTitles.display(info.rawName)} (${info.pages} صفحة)",
                    modifier = Modifier.testTag("embedded_book_line"),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = DesignFonts.ArabicUiFamily
                )
            }
        }

        Text(
            "أسئلة أمثلة",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onBackground,
            fontFamily = DesignFonts.ArabicUiFamily
        )

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            EXAMPLE_QUESTIONS.forEachIndexed { index, question ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .testTag("example_$index")
                        .clip(RoundedCornerShape(extendedTokens.cardRadius))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .border(
                            width = 1.dp,
                            color = extendedTokens.hairlineBorderColor,
                            shape = RoundedCornerShape(extendedTokens.cardRadius)
                        )
                        .clickable(role = Role.Button) { onExample(question) }
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = question,
                        style = MaterialTheme.typography.bodyMedium.copy(
                            textDirection = TextDirection.Ltr
                        ),
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f)
                    )
                    Icon(
                        imageVector = EXAMPLE_ICONS[index % EXAMPLE_ICONS.size],
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .padding(start = 8.dp)
                            .size(20.dp)
                    )
                }
            }
        }
    }
}

@Composable
private fun SearchingCard(question: String, onCancel: () -> Unit) {
    val extendedTokens = LocalExtendedDesignTokens.current
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("searching_state"),
        shape = RoundedCornerShape(extendedTokens.cardRadius),
        color = MaterialTheme.colorScheme.surfaceVariant,
        border = BorderStroke(1.dp, extendedTokens.hairlineBorderColor)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.5.dp,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    "جارٍ البحث…",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            LinearProgressIndicator(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp)),
                color = MaterialTheme.colorScheme.primary,
                trackColor = extendedTokens.hairlineBorderColor
            )
            Text(
                question,
                style = MaterialTheme.typography.bodyMedium.copy(
                    textDirection = if (PassageText.isMostlyLatin(question)) {
                        TextDirection.Ltr
                    } else {
                        TextDirection.Rtl
                    }
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            TextButton(
                onClick = onCancel,
                modifier = Modifier.heightIn(min = 48.dp)
            ) {
                Text(
                    "إلغاء",
                    fontFamily = DesignFonts.ArabicUiFamily,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

@Composable
private fun TimingLine(timing: AskTiming) {
    Text(
        "Tokenize ${timing.tokenizeMs} ms · Embed ${timing.embedMs} ms · " +
            "Search ${timing.searchMs} ms · Total ${timing.totalMs} ms",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
}

@Composable
private fun RefusalCardView(
    refusal: String,
    onShowNearest: (() -> Unit)? = null
) {
    val extendedTokens = LocalExtendedDesignTokens.current
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("refusal_card"),
        shape = RoundedCornerShape(extendedTokens.cardRadius),
        color = MaterialTheme.colorScheme.surfaceVariant,
        border = BorderStroke(1.dp, extendedTokens.hairlineBorderColor)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .clip(RoundedCornerShape(extendedTokens.chipRadius))
                        .background(MaterialTheme.colorScheme.errorContainer),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        imageVector = Icons.Outlined.Info,
                        contentDescription = "تنبيه معلوماتي",
                        tint = MaterialTheme.colorScheme.error,
                        modifier = Modifier.size(24.dp)
                    )
                }
                Text(
                    text = "توضيح مرجعي",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = DesignFonts.ArabicUiFamily
                )
            }

            Text(
                text = refusal,
                modifier = Modifier.testTag("refusal_text"),
                style = MaterialTheme.typography.bodyLarge.copy(
                    textDirection = TextDirection.Rtl
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = FontWeight.Bold,
                fontFamily = DesignFonts.ArabicUiFamily
            )

            if (onShowNearest != null) {
                OutlinedButton(
                    onClick = onShowNearest,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .testTag("show_nearest_button")
                ) {
                    Text(
                        text = "عرض أقرب النتائج",
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                        fontFamily = DesignFonts.ArabicUiFamily
                    )
                }
            }
        }
    }
}

@Composable
private fun ErrorCard(message: String, onRetry: () -> Unit) {
    val extendedTokens = LocalExtendedDesignTokens.current
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(extendedTokens.cardRadius),
        color = MaterialTheme.colorScheme.errorContainer,
        border = BorderStroke(1.dp, extendedTokens.hairlineBorderColor)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                "حدث خطأ",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onErrorContainer
            )
            Text(
                message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onErrorContainer
            )
            Button(
                onClick = onRetry,
                modifier = Modifier.heightIn(min = 48.dp)
            ) {
                Text(
                    "إعادة المحاولة",
                    fontFamily = DesignFonts.ArabicUiFamily,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ResultList(
    passages: List<Passage>,
    showDiagnostics: Boolean,
    firstCardRequester: BringIntoViewRequester,
    onCitationClick: (Passage) -> Unit,
    onCopy: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        passages.forEachIndexed { index, passage ->
            StaggeredCardEnter(index = index) {
                ResultCard(
                    passage = passage,
                    showDiagnostics = showDiagnostics,
                    modifier = if (index == 0) {
                        Modifier.bringIntoViewRequester(firstCardRequester)
                    } else {
                        Modifier
                    },
                    onCitationClick = onCitationClick,
                    onCopy = onCopy
                )
            }
        }
    }
}

@Composable
private fun ResultCard(
    passage: Passage,
    showDiagnostics: Boolean,
    modifier: Modifier = Modifier,
    onCitationClick: (Passage) -> Unit,
    onCopy: (String) -> Unit
) {
    val extendedTokens = LocalExtendedDesignTokens.current
    var expanded by rememberSaveable(passage.chunkId) { mutableStateOf(false) }
    var copied by rememberSaveable(passage.chunkId) { mutableStateOf(false) }
    val preview = remember(passage.text) { PassageText.truncateAtWord(passage.text) }
    val shown = if (expanded) passage.text else preview.text
    val ranges = remember(shown, passage.highlightRanges) {
        passage.highlightRanges.filter { it.first >= 0 && it.last < shown.length }
    }

    LaunchedEffect(copied) {
        if (copied) {
            delay(2000)
            copied = false
        }
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .testTag("result_card_${passage.chunkId}")
            .clip(RoundedCornerShape(extendedTokens.cardRadius))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .border(
                width = 1.dp,
                color = extendedTokens.hairlineBorderColor,
                shape = RoundedCornerShape(extendedTokens.cardRadius)
            )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(IntrinsicSize.Min)
        ) {
            // Margin rail along start edge
            Box(
                modifier = Modifier
                    .width(4.dp)
                    .fillMaxHeight()
                    .background(extendedTokens.marginRailColor)
            )

            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                // Header: Bookmark tab + Rank chip + diagnostics score
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        // Bookmark tab
                        Box(
                            modifier = Modifier
                                .testTag("page_chip_${passage.chunkId}")
                                .clip(RoundedCornerShape(extendedTokens.chipRadius))
                                .background(extendedTokens.bookmarkTabBackground)
                                .clickable { onCitationClick(passage) }
                                .padding(horizontal = 8.dp, vertical = 4.dp)
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp)
                            ) {
                                Text(
                                    text = "ص",
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.Bold,
                                    color = extendedTokens.bookmarkTabText,
                                    fontFamily = DesignFonts.ArabicUiFamily
                                )
                                Text(
                                    text = passage.page.toString(),
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.Bold,
                                    color = extendedTokens.bookmarkTabText
                                )
                            }
                        }

                        // Rank chip
                        Box(
                            modifier = Modifier
                                .testTag("rank_chip_${passage.chunkId}")
                                .clip(RoundedCornerShape(extendedTokens.chipRadius))
                                .background(extendedTokens.rankChipBackground)
                                .padding(horizontal = 8.dp, vertical = 4.dp)
                        ) {
                            Text(
                                text = "#${passage.rank}",
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold,
                                color = extendedTokens.rankChipText
                            )
                        }
                    }

                    if (showDiagnostics) {
                        Text(
                            String.format(Locale.ROOT, "cos %.4f", passage.score),
                            modifier = Modifier.testTag("score_${passage.chunkId}"),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }

                // CitationLine
                CitationLine(
                    bookTitle = BookTitles.display(passage.bookName),
                    page = passage.page,
                    onClick = { onCitationClick(passage) },
                    testTag = "citation_${passage.chunkId}",
                    showPage = false
                )

                // Hairline divider
                HorizontalDivider(
                    thickness = 0.75.dp,
                    color = extendedTokens.subtleDividerColor
                )

                // PassageBody in Source Serif 4
                PassageBody(
                    text = shown,
                    ranges = ranges,
                    tagPrefix = "passage_body_${passage.chunkId}"
                )

                // Footer: toggle + copy button
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    if (preview.truncated) {
                        Text(
                            text = if (expanded) "عرض أقل" else "عرض المزيد",
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary,
                            fontFamily = DesignFonts.ArabicUiFamily,
                            modifier = Modifier
                                .testTag("expand_${passage.chunkId}")
                                .clickable { expanded = !expanded }
                                .padding(vertical = 4.dp)
                        )
                    } else {
                        Spacer(modifier = Modifier.width(1.dp))
                    }

                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        if (copied) {
                            Text(
                                "تم النسخ",
                                modifier = Modifier.testTag("copy_feedback_${passage.chunkId}"),
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.primary,
                                fontFamily = DesignFonts.ArabicUiFamily
                            )
                        }
                        IconButton(
                            onClick = {
                                onCopy(passage.text)
                                copied = true
                            },
                            modifier = Modifier
                                .size(48.dp)
                                .testTag("copy_result_${passage.chunkId}")
                        ) {
                            Icon(
                                painter = painterResource(R.drawable.ic_copy),
                                contentDescription = "نسخ المقطع",
                                modifier = Modifier.size(20.dp),
                                tint = MaterialTheme.colorScheme.primary
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PassageBody(text: String, ranges: List<IntRange>, tagPrefix: String) {
    val extendedTokens = LocalExtendedDesignTokens.current
    val background = extendedTokens.markerHighlightBackground
    val foreground = extendedTokens.markerHighlightText
    val annotated = remember(text, ranges, background, foreground) {
        buildAnnotatedString {
            append(text)
            ranges.forEach { range ->
                val start = range.first.coerceIn(0, text.length)
                val end = (range.last + 1).coerceIn(start, text.length)
                if (start < end) {
                    addStyle(
                        SpanStyle(
                            background = background,
                            color = foreground,
                            fontWeight = FontWeight.Bold
                        ),
                        start,
                        end
                    )
                }
            }
        }
    }
    val ltr = PassageText.isMostlyLatin(text)
    Text(
        text = annotated,
        modifier = Modifier.testTag("${tagPrefix}_${if (ltr) "ltr" else "rtl"}"),
        fontFamily = if (ltr) DesignFonts.EnglishBookPassageFamily else DesignFonts.ArabicUiFamily,
        style = MaterialTheme.typography.bodyLarge.copy(
            fontSize = 15.sp,
            lineHeight = 23.sp,
            textDirection = if (ltr) TextDirection.Ltr else TextDirection.Rtl
        ),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = if (ltr) TextAlign.Left else TextAlign.Right
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PassageSheet(
    initial: Passage,
    onDismiss: () -> Unit,
    onNeighbour: suspend (Int, Int) -> Passage?,
    onCopy: (String) -> Unit
) {
    val extendedTokens = LocalExtendedDesignTokens.current
    var current by remember(initial.chunkId) { mutableStateOf(initial) }
    var previous by remember { mutableStateOf<Passage?>(null) }
    var next by remember { mutableStateOf<Passage?>(null) }
    var loading by remember { mutableStateOf(true) }
    var copied by remember { mutableStateOf(false) }
    val bodyScroll = rememberScrollState()
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    LaunchedEffect(current.chunkId) {
        loading = true
        bodyScroll.scrollTo(0)
        previous = try {
            onNeighbour(current.chunkId, -1)
        } catch (_: Throwable) {
            null
        }
        next = try {
            onNeighbour(current.chunkId, 1)
        } catch (_: Throwable) {
            null
        }
        loading = false
    }
    LaunchedEffect(copied) {
        if (copied) {
            delay(2000)
            copied = false
        }
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        shape = RoundedCornerShape(
            topStart = extendedTokens.sheetRadius,
            topEnd = extendedTokens.sheetRadius
        ),
        containerColor = MaterialTheme.colorScheme.surface
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .fillMaxHeight(0.85f)
        ) {
            // Pinned header
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 24.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        "المقطع الكامل",
                        modifier = Modifier
                            .weight(1f)
                            .testTag("sheet_title"),
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        fontFamily = DesignFonts.ArabicUiFamily,
                        color = MaterialTheme.colorScheme.onSurface
                    )
                    IconButton(
                        onClick = onDismiss,
                        modifier = Modifier
                            .size(48.dp)
                            .testTag("sheet_close")
                    ) {
                        Icon(
                            Icons.Filled.Close,
                            contentDescription = "إغلاق",
                            tint = MaterialTheme.colorScheme.onSurface
                        )
                    }
                }
                CitationLine(
                    bookTitle = BookTitles.display(current.bookName),
                    page = current.page,
                    testTag = "sheet_citation",
                    showPage = true
                )
                Text(
                    positionLine(current),
                    modifier = Modifier.testTag("sheet_position"),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = DesignFonts.ArabicUiFamily
                )
            }
            HorizontalDivider(
                thickness = 1.dp,
                color = extendedTokens.hairlineBorderColor
            )
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .verticalScroll(bodyScroll)
                    .padding(horizontal = 24.dp, vertical = 12.dp)
                    .testTag("sheet_body")
            ) {
                PassageBody(current.text, emptyList(), "sheet_body_${current.chunkId}")
                Spacer(modifier = Modifier.height(96.dp))
            }
            HorizontalDivider(
                thickness = 1.dp,
                color = extendedTokens.hairlineBorderColor
            )
            // Pinned footer
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    OutlinedButton(
                        onClick = { previous?.let { current = it } },
                        enabled = previous != null && !loading,
                        modifier = Modifier
                            .weight(1f)
                            .heightIn(min = 48.dp)
                            .testTag("sheet_prev"),
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp)
                    ) {
                        Text(
                            neighbourLabel("السابق", previous),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.labelMedium,
                            fontFamily = DesignFonts.ArabicUiFamily,
                            fontWeight = FontWeight.Bold
                        )
                    }
                    OutlinedButton(
                        onClick = { next?.let { current = it } },
                        enabled = next != null && !loading,
                        modifier = Modifier
                            .weight(1f)
                            .heightIn(min = 48.dp)
                            .testTag("sheet_next"),
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp)
                    ) {
                        Text(
                            neighbourLabel("التالي", next),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.labelMedium,
                            fontFamily = DesignFonts.ArabicUiFamily,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    TextButton(
                        onClick = {
                            onCopy(current.text)
                            copied = true
                        },
                        modifier = Modifier.heightIn(min = 48.dp)
                    ) {
                        Text(
                            "نسخ النص",
                            fontFamily = DesignFonts.ArabicUiFamily,
                            fontWeight = FontWeight.Bold
                        )
                    }
                    if (copied) {
                        Text(
                            "تم النسخ",
                            modifier = Modifier.testTag("sheet_copy_feedback"),
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary,
                            fontFamily = DesignFonts.ArabicUiFamily
                        )
                    }
                }
            }
        }
    }
}

private fun positionLine(passage: Passage): String {
    return if (passage.positionInBook > 0 && passage.totalInBook > 0) {
        "فقرة ${passage.positionInBook} من ${passage.totalInBook} في الكتاب"
    } else {
        "فقرة غير معروفة في الكتاب"
    }
}

private fun neighbourLabel(label: String, passage: Passage?): String {
    return if (passage != null) "$label · ص ${passage.page}" else label
}
