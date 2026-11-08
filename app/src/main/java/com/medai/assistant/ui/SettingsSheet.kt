package com.medai.assistant.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
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
import com.medai.assistant.settings.AppSettings
import kotlinx.coroutines.delay

/**
 * The only settings allowed by K5a/K5c: refusal-gate preset, whether timings
 * and cosine scores are visible, and the diagnostics report copy action.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsSheet(
    settings: AppSettings,
    onPreset: (String) -> Unit,
    onShowTimings: (Boolean) -> Unit,
    onCopyReport: () -> Unit,
    onDismiss: () -> Unit
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(copied) {
        if (copied) {
            delay(2000)
            copied = false
        }
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
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
                fontWeight = FontWeight.Bold
            )

            Text(
                "درجة التشدد في فلتر الرفض",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
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
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        "وضع التشخيص: يعرض زمن البحث ودرجة التشابه.",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                Switch(
                    checked = settings.showTimings,
                    onCheckedChange = onShowTimings,
                    modifier = Modifier.testTag("show_timings_switch")
                )
            }

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
                Text(if (copied) "تم النسخ" else "نسخ تقرير التشخيص")
            }
            TextButton(
                onClick = onDismiss,
                modifier = Modifier
                    .heightIn(min = 48.dp)
                    .testTag("settings_close")
            ) {
                Text("إغلاق")
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
            Text(label, style = MaterialTheme.typography.bodyLarge)
            Text(description, style = MaterialTheme.typography.bodySmall)
        }
    }
}
