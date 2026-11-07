package com.medai.assistant.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.dp
import com.medai.assistant.ask.AskState
import com.medai.assistant.ask.AskTiming
import com.medai.assistant.ask.AskViewModel
import com.medai.assistant.ask.Passage
import com.medai.assistant.ask.PassageText
import com.medai.assistant.settings.AppSettings
import kotlinx.coroutines.launch

/** Four real golden questions used by the empty state (golden ids 44, 41, 42, 43). */
val EXAMPLE_QUESTIONS = listOf(
    "What causes bacterial vaginosis?",
    "When is the best time to insert an IUD?",
    "What are the potential complications of IUD use?",
    "What options are available for emergency contraception?"
)

@OptIn(ExperimentalMaterial3Api::class)
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

    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val clipboard = LocalClipboardManager.current
    val copy: (String) -> Unit = { text ->
        clipboard.setText(AnnotatedString(text))
        scope.launch { snackbar.showSnackbar("تم نسخ النص") }
    }
    val submit: () -> Unit = {
        val question = input.trim()
        if (question.isNotEmpty()) viewModel.ask(question)
    }
    val canSubmit = state !is AskState.Installing && state !is AskState.LoadingModel

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        contentWindowInsets = WindowInsets.safeDrawing,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "المساعد الطبي",
                        modifier = Modifier
                            .pointerInput(Unit) {
                                detectTapGestures(onLongPress = { onOpenDebug() })
                            }
                            .padding(vertical = 12.dp)
                    )
                },
                actions = {
                    TextButton(
                        onClick = { showSettings = true },
                        modifier = Modifier.heightIn(min = 48.dp)
                    ) {
                        Text("الإعدادات")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                    titleContentColor = MaterialTheme.colorScheme.onPrimaryContainer
                )
            )
        },
        bottomBar = {
            AskInputBar(
                value = input,
                onValueChange = { input = it },
                canSubmit = canSubmit,
                onSubmit = submit
            )
        },
        snackbarHost = { SnackbarHost(snackbar) }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            when (val current = state) {
                is AskState.Installing -> InstallingCard(current)
                is AskState.LoadingModel -> LoadingModelCard()
                is AskState.Ready -> EmptyState(onExample = { input = it })
                is AskState.Searching -> SearchingCard(
                    question = current.question,
                    onCancel = viewModel::cancel
                )
                is AskState.Results -> {
                    QuestionHeader(current.question)
                    if (settings.showTimings) TimingLine(current.timings)
                    current.top3.forEach { passage ->
                        ResultCard(
                            passage = passage,
                            onCitationClick = { sheetPassage = it },
                            onCopy = copy
                        )
                    }
                }
                is AskState.Rejected -> {
                    QuestionHeader(current.question)
                    if (settings.showTimings) TimingLine(current.timings)
                    RefusalCard(current.refusal)
                    var expanded by rememberSaveable(current.question) { mutableStateOf(false) }
                    if (!expanded) {
                        OutlinedButton(
                            onClick = { expanded = true },
                            modifier = Modifier
                                .fillMaxWidth()
                                .heightIn(min = 48.dp)
                        ) {
                            Text("عرض أقرب النتائج")
                        }
                    } else {
                        TextButton(
                            onClick = { expanded = false },
                            modifier = Modifier.heightIn(min = 48.dp)
                        ) {
                            Text("إخفاء أقرب النتائج")
                        }
                        current.top3.forEach { passage ->
                            ResultCard(
                                passage = passage,
                                onCitationClick = { sheetPassage = it },
                                onCopy = copy
                            )
                        }
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
            onPreset = viewModel::setPreset,
            onShowTimings = viewModel::setShowTimings,
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
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                "تجهيز التطبيق",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            Text(
                "يتم نسخ الملفات الكبيرة مرة واحدة فقط.",
                style = MaterialTheme.typography.bodySmall
            )
            LinearProgressIndicator(
                progress = { fraction },
                modifier = Modifier.fillMaxWidth()
            )
            Text(
                "${state.fileName} — ${(fraction * 100).toInt()}%",
                style = MaterialTheme.typography.bodySmall
            )
            Text(
                "${state.doneBytes} / ${state.totalBytes} بايت",
                style = MaterialTheme.typography.bodySmall
            )
        }
    }
}

@Composable
private fun LoadingModelCard() {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            CircularProgressIndicator()
            Text(
                "جارٍ تحميل النموذج...",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            Text(
                "يتم التحميل في الخلفية، ويمكنك كتابة سؤالك الآن.",
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
private fun EmptyState(onExample: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            "اسأل عن أي موضوع في كتاب النساء والتوليد المدمج في التطبيق.",
            style = MaterialTheme.typography.bodyLarge
        )
        Text(
            "أسئلة أمثلة",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold
        )
        EXAMPLE_QUESTIONS.forEach { question ->
            OutlinedButton(
                onClick = { onExample(question) },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
            ) {
                Text(
                    question,
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.labelLarge.copy(
                        textDirection = TextDirection.Ltr
                    ),
                    textAlign = TextAlign.Left
                )
            }
        }
    }
}

@Composable
private fun SearchingCard(question: String, onCancel: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            Text(
                "جارٍ البحث...",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            Text(question, style = MaterialTheme.typography.bodyMedium)
            TextButton(
                onClick = onCancel,
                modifier = Modifier.heightIn(min = 48.dp)
            ) {
                Text("إلغاء")
            }
        }
    }
}

@Composable
private fun QuestionHeader(question: String) {
    Text(
        question,
        style = MaterialTheme.typography.titleMedium.copy(
            textDirection = TextDirection.Content
        ),
        fontWeight = FontWeight.Bold
    )
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
private fun RefusalCard(refusal: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
            contentColor = MaterialTheme.colorScheme.onErrorContainer
        )
    ) {
        Text(
            refusal,
            modifier = Modifier.padding(16.dp),
            style = MaterialTheme.typography.bodyLarge.copy(
                textDirection = TextDirection.Rtl
            ),
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
private fun ErrorCard(message: String, onRetry: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
            contentColor = MaterialTheme.colorScheme.onErrorContainer
        )
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                "حدث خطأ",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            Text(message, style = MaterialTheme.typography.bodyMedium)
            Button(
                onClick = onRetry,
                modifier = Modifier.heightIn(min = 48.dp)
            ) {
                Text("إعادة المحاولة")
            }
        }
    }
}

@Composable
private fun ResultCard(
    passage: Passage,
    onCitationClick: (Passage) -> Unit,
    onCopy: (String) -> Unit
) {
    var expanded by rememberSaveable(passage.chunkId) { mutableStateOf(false) }
    val preview = remember(passage.text) { PassageText.truncateAtWord(passage.text) }
    val shown = if (expanded) passage.text else preview.text
    val ranges = remember(shown, passage.highlightRanges) {
        passage.highlightRanges.filter { it.first >= 0 && it.last < shown.length }
    }

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.Top
            ) {
                Text(
                    "#${passage.rank}",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    PassageText.citation(passage.bookName, passage.page),
                    modifier = Modifier
                        .weight(1f)
                        .clickable { onCitationClick(passage) }
                        .heightIn(min = 48.dp)
                        .padding(vertical = 12.dp),
                    style = MaterialTheme.typography.labelLarge.copy(
                        textDirection = TextDirection.Content
                    ),
                    color = MaterialTheme.colorScheme.primary
                )
            }
            PassageBody(shown, ranges)
            if (preview.truncated) {
                TextButton(
                    onClick = { expanded = !expanded },
                    modifier = Modifier.heightIn(min = 48.dp)
                ) {
                    Text(if (expanded) "عرض أقل" else "عرض المزيد")
                }
            }
            HorizontalDivider()
            TextButton(
                onClick = { onCopy(passage.text) },
                modifier = Modifier.heightIn(min = 48.dp)
            ) {
                Text("نسخ النص")
            }
        }
    }
}

@Composable
private fun PassageBody(text: String, ranges: List<IntRange>) {
    val background = MaterialTheme.colorScheme.tertiaryContainer
    val foreground = MaterialTheme.colorScheme.onTertiaryContainer
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
                            fontWeight = FontWeight.SemiBold
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
        style = MaterialTheme.typography.bodyMedium.copy(
            textDirection = if (ltr) TextDirection.Ltr else TextDirection.Rtl
        ),
        textAlign = if (ltr) TextAlign.Left else TextAlign.Right
    )
}

@Composable
private fun AskInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    canSubmit: Boolean,
    onSubmit: () -> Unit
) {
    Surface(tonalElevation = 3.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .imePadding()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                placeholder = { Text("اكتب سؤالك الطبي...") },
                minLines = 1,
                maxLines = 4,
                textStyle = LocalTextStyle.current.copy(
                    textDirection = TextDirection.Content
                ),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { onSubmit() })
            )
            Button(
                onClick = onSubmit,
                enabled = canSubmit && value.isNotBlank(),
                modifier = Modifier
                    .heightIn(min = 48.dp)
                    .widthIn(min = 48.dp)
            ) {
                Text("إرسال")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PassageSheet(
    initial: Passage,
    onDismiss: () -> Unit,
    onNeighbour: suspend (Int, Int) -> Passage?,
    onCopy: (String) -> Unit
) {
    var current by remember(initial.chunkId) { mutableStateOf(initial) }
    var previous by remember { mutableStateOf<Passage?>(null) }
    var next by remember { mutableStateOf<Passage?>(null) }
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(current.chunkId) {
        loading = true
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

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                "المقطع الكامل",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold
            )
            Text(
                PassageText.citation(current.bookName, current.page),
                style = MaterialTheme.typography.labelLarge.copy(
                    textDirection = TextDirection.Content
                ),
                color = MaterialTheme.colorScheme.primary
            )
            PassageBody(current.text, emptyList())
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
                ) {
                    Text("السابق")
                }
                OutlinedButton(
                    onClick = { next?.let { current = it } },
                    enabled = next != null && !loading,
                    modifier = Modifier
                        .weight(1f)
                        .heightIn(min = 48.dp)
                ) {
                    Text("التالي")
                }
            }
            Button(
                onClick = { onCopy(current.text) },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
            ) {
                Text("نسخ النص")
            }
        }
    }
}
