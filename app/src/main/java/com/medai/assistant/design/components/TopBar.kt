package com.medai.assistant.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens

/**
 * TopBar according to STAGE UI-A item 4:
 * App title, subtitle ("يجيب من الكتاب المدمج فقط · بدون إنترنت"), settings icon, and small offline badge.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MedAiTopBar(
    onSettingsClick: () -> Unit,
    modifier: Modifier = Modifier,
    title: String = "المساعد الطبي",
    subtitle: String = "يجيب من الكتاب المدمج فقط · بدون إنترنت",
    testTag: String = "medai_top_bar"
) {
    val extendedTokens = LocalExtendedDesignTokens.current

    TopAppBar(
        modifier = modifier.testTag(testTag),
        title = {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(DesignSpacing.space8)
                ) {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontFamily = DesignFonts.ArabicUiFamily
                    )

                    // Small offline badge
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(extendedTokens.chipRadius))
                            .background(extendedTokens.offlineBadgeBackground)
                            .padding(horizontal = DesignSpacing.space8, vertical = 2.dp)
                    ) {
                        Text(
                            text = "بدون إنترنت",
                            style = MaterialTheme.typography.labelSmall.copy(fontSize = 10.sp),
                            fontWeight = FontWeight.Bold,
                            color = extendedTokens.offlineBadgeText,
                            fontFamily = DesignFonts.ArabicUiFamily
                        )
                    }
                }

                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.sp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = DesignFonts.ArabicUiFamily
                )
            }
        },
        actions = {
            IconButton(
                onClick = onSettingsClick,
                modifier = Modifier
                    .size(48.dp) // Touch target >= 48dp
                    .testTag("settings_button")
            ) {
                Icon(
                    imageVector = Icons.Outlined.Settings,
                    contentDescription = "الإعدادات",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surface,
            titleContentColor = MaterialTheme.colorScheme.onSurface,
            actionIconContentColor = MaterialTheme.colorScheme.onSurfaceVariant
        )
    )
}
