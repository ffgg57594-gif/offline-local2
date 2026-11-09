package com.medai.assistant.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens

/**
 * Calm informational refusal card displaying the exact sentence:
 * "هذه المعلومة غير مذكورة في الكتب الطبية المدمجة في التطبيق."
 * with a secondary "عرض أقرب النتائج" control.
 */
@Composable
fun RefusalCard(
    modifier: Modifier = Modifier,
    onShowNearestClick: (() -> Unit)? = null,
    testTag: String = "refusal_card"
) {
    val extendedTokens = LocalExtendedDesignTokens.current

    Box(
        modifier = modifier
            .fillMaxWidth()
            .testTag(testTag)
            .clip(RoundedCornerShape(extendedTokens.cardRadius))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .border(
                width = 1.dp,
                color = extendedTokens.hairlineBorderColor,
                shape = RoundedCornerShape(extendedTokens.cardRadius)
            )
            .padding(DesignSpacing.space16)
    ) {
        Column(
            verticalArrangement = Arrangement.spacedBy(DesignSpacing.space12)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(DesignSpacing.space12)
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
                text = "هذه المعلومة غير مذكورة في الكتب الطبية المدمجة في التطبيق.",
                modifier = Modifier.testTag("refusal_text"),
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontFamily = DesignFonts.ArabicUiFamily
            )

            if (onShowNearestClick != null) {
                OutlinedButton(
                    onClick = onShowNearestClick,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp) // Touch target >= 48dp
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
