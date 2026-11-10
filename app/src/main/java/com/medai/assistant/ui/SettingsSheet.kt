package com.medai.assistant.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.LocalExtendedDesignTokens
import com.medai.assistant.llm.CatalogModel
import com.medai.assistant.llm.ModelState
import com.medai.assistant.settings.AppSettings
import kotlinx.coroutines.delay
import java.util.Locale

/**
 * The only settings allowed by K5a/K5c: refusal-gate preset, whether timings
 * and cosine scores are visible, and the diagnostics report copy action.
 * K7a adds the "الموديل" section for the in-app LLM model download.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsSheet(
    settings: AppSettings,
    modelStates: Map<String, ModelState>,
    catalogModels: List<CatalogModel>,
    onDownload: (CatalogModel) -> Unit,
    onCancelDownload: (String) -> Unit,
    onDeleteModel: (String) -> Unit,
    onImportModel: () -> Unit,
    onPreset: (String) -> Unit,
    onShowTimings: (Boolean) -> Unit,
    onCopyReport: () -> Unit,
    onDismiss: () -> Unit
) {
    val extendedTokens = LocalExtendedDesignTokens.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var copied by remember { mutableStateOf(false) }
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
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text(
                "الإعدادات",
                modifier = Modifier.testTag("settings_sheet_title"),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onSurface
            )

            Text(
                "درجة التشدد في فلتر الرفض",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onSurface
            )
            PresetRow(
                label = "متوازن",
                description = "يقبل أسئلة أكثر مع الحفاظ على رفض ما ليس في الكتاب.",
                selected = settings.preset == AppSettings.BALANCED,
                onSelect = { onPreset(AppSettings.BALANCED) },
                testTag = "preset_balanced"
            )
            PresetRow(
                label = "صارم",
                description = "يرفض أكثر عندما لا تكون الإجابة واضحة في الكتاب.",
                selected = settings.preset == AppSettings.STRICT,
                onSelect = { onPreset(AppSettings.STRICT) },
                testTag = "preset_strict"
            )

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "إظهار التوقيتات",
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.SemiBold,
                        fontFamily = DesignFonts.ArabicUiFamily,
                        color = MaterialTheme.colorScheme.onSurface
                    )
                    Text(
                        "وضع التشخيص: يعرض زمن البحث ودرجة التشابه.",
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = DesignFonts.ArabicUiFamily,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(
                    checked = settings.showTimings,
                    onCheckedChange = onShowTimings,
                    modifier = Modifier.testTag("show_timings_switch")
                )
            }

            HorizontalDivider()

            ModelSection(
                modelStates = modelStates,
                catalogModels = catalogModels,
                onDownload = onDownload,
                onCancelDownload = onCancelDownload,
                onDeleteModel = onDeleteModel,
                onImportModel = onImportModel
            )

            Button(
                onClick = {
                    onCopyReport()
                    copied = true
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .testTag("copy_diagnostics")
            ) {
                Text(
                    if (copied) "تم النسخ" else "نسخ تقرير التشخيص",
                    fontFamily = DesignFonts.ArabicUiFamily,
                    fontWeight = FontWeight.Bold
                )
            }
            TextButton(
                onClick = onDismiss,
                modifier = Modifier
                    .heightIn(min = 48.dp)
                    .testTag("settings_close")
            ) {
                Text(
                    "إغلاق",
                    fontFamily = DesignFonts.ArabicUiFamily,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

@Composable
private fun PresetRow(
    label: String,
    description: String,
    selected: Boolean,
    onSelect: () -> Unit,
    testTag: String
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp)
            .testTag(testTag)
            .selectable(
                selected = selected,
                onClick = onSelect,
                role = Role.RadioButton
            ),
        verticalAlignment = Alignment.CenterVertically
    ) {
        RadioButton(selected = selected, onClick = null)
        Column(modifier = Modifier.padding(start = 12.dp)) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge,
                fontFamily = DesignFonts.ArabicUiFamily,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                description,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/**
 * K7a: the "الموديل" section. Shows every catalog model with its state:
 * not installed, downloading (percent + MB), verifying, ready, or error.
 * Import via SAF accepts only files whose sha256 equals a catalog entry.
 */
@Composable
private fun ModelSection(
    modelStates: Map<String, ModelState>,
    catalogModels: List<CatalogModel>,
    onDownload: (CatalogModel) -> Unit,
    onCancelDownload: (String) -> Unit,
    onDeleteModel: (String) -> Unit,
    onImportModel: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("model_section"),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            "الموديل (الذكاء الاصطناعي)",
            modifier = Modifier.testTag("model_section_title"),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            fontFamily = DesignFonts.ArabicUiFamily,
            color = MaterialTheme.colorScheme.onSurface
        )
        Text(
            "موديل لغة يُنزَّل داخل التطبيق ويشتغل بلا إنترنت بعد التنزيل. " +
                "التحقق من البصمة (sha256) يتم قبل الاستخدام.",
            style = MaterialTheme.typography.bodySmall,
            fontFamily = DesignFonts.ArabicUiFamily,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        for (model in catalogModels) {
            ModelRow(
                model = model,
                state = modelStates[model.id] ?: ModelState.NotInstalled,
                onDownload = onDownload,
                onCancelDownload = onCancelDownload,
                onDeleteModel = onDeleteModel
            )
        }

        OutlinedButton(
            onClick = onImportModel,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp)
                .testTag("model_import")
        ) {
            Text(
                "استيراد من الملفات",
                fontFamily = DesignFonts.ArabicUiFamily,
                fontWeight = FontWeight.Bold
            )
        }

        Text(
            "الإنترنت يُستخدم لتحميل الموديل فقط.",
            modifier = Modifier.testTag("model_internet_note"),
            style = MaterialTheme.typography.bodySmall,
            fontFamily = DesignFonts.ArabicUiFamily,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun ModelRow(
    model: CatalogModel,
    state: ModelState,
    onDownload: (CatalogModel) -> Unit,
    onCancelDownload: (String) -> Unit,
    onDeleteModel: (String) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("model_item_${model.id}"),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                model.displayName,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.weight(1f, fill = false)
            )
            Text(
                stateLabel(state),
                modifier = Modifier.testTag("model_state_${model.id}"),
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
                fontFamily = DesignFonts.ArabicUiFamily,
                color = stateColor(state)
            )
        }
        Text(
            "الحجم: ${model.sizeBytes / (1024 * 1024)} ميجابايت — " +
                "الترخيص: ${model.license} — تقدير الذاكرة: " +
                "${model.ramEstimateMb} ميجابايت",
            style = MaterialTheme.typography.bodySmall,
            fontFamily = DesignFonts.ArabicUiFamily,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        when (state) {
            ModelState.NotInstalled -> {
                Text(
                    if (model.isDefault) {
                        "حوالي ${model.sizeBytes / (1024 * 1024)} ميجابايت، يفضل Wi-Fi."
                    } else {
                        "نسخة أصغر وأسرع كخيار بديل (حوالي " +
                            "${model.sizeBytes / (1024 * 1024)} ميجابايت)."
                    },
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Button(
                    onClick = { onDownload(model) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .testTag("model_download_${model.id}")
                ) {
                    Text(
                        "تنزيل",
                        fontFamily = DesignFonts.ArabicUiFamily,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
            is ModelState.Downloading -> {
                val fraction = if (state.totalBytes > 0) {
                    (state.bytesSoFar.toFloat() / state.totalBytes.toFloat())
                        .coerceIn(0f, 1f)
                } else {
                    0f
                }
                LinearProgressIndicator(
                    progress = { fraction },
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("model_progress_${model.id}")
                )
                Text(
                    String.format(
                        Locale.US,
                        "%d%% (%d من %d ميجابايت)",
                        (fraction * 100).toInt(),
                        state.bytesSoFar / (1024 * 1024),
                        state.totalBytes / (1024 * 1024)
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                OutlinedButton(
                    onClick = { onCancelDownload(model.id) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .testTag("model_cancel_${model.id}")
                ) {
                    Text(
                        "إلغاء التنزيل",
                        fontFamily = DesignFonts.ArabicUiFamily,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
            is ModelState.Verifying -> {
                Text(
                    "جاري التحقق من بصمة الملف (sha256)...",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            is ModelState.Ready -> {
                Text(
                    "جاهز — ${state.fileName} " +
                        "(${state.sizeBytes / (1024 * 1024)} ميجابايت على القرص)",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.primary
                )
                OutlinedButton(
                    onClick = { onDeleteModel(model.id) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .testTag("model_delete_${model.id}")
                ) {
                    Text(
                        "حذف الموديل",
                        fontFamily = DesignFonts.ArabicUiFamily,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
            is ModelState.Error -> {
                Text(
                    state.message,
                    modifier = Modifier.testTag("model_error_${model.id}"),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = DesignFonts.ArabicUiFamily,
                    color = MaterialTheme.colorScheme.error
                )
                Button(
                    onClick = { onDownload(model) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .testTag("model_retry_${model.id}")
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
}

private fun stateLabel(state: ModelState): String = when (state) {
    ModelState.NotInstalled -> "غير مثبت"
    is ModelState.Downloading -> "ينزّل الآن"
    is ModelState.Verifying -> "جاري التحقق"
    is ModelState.Ready -> "جاهز"
    is ModelState.Error -> "خطأ"
}

@Composable
private fun stateColor(state: ModelState) = when (state) {
    ModelState.NotInstalled -> MaterialTheme.colorScheme.onSurfaceVariant
    is ModelState.Downloading -> MaterialTheme.colorScheme.primary
    is ModelState.Verifying -> MaterialTheme.colorScheme.primary
    is ModelState.Ready -> MaterialTheme.colorScheme.primary
    is ModelState.Error -> MaterialTheme.colorScheme.error
}

