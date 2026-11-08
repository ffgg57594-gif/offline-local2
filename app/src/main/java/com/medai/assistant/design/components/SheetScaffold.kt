package com.medai.assistant.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens

/**
 * SheetScaffold according to STAGE UI-A item 4:
 * Pinned header (title, citation, close), scrollable body, pinned footer with "السابق" and "التالي".
 */
@Composable
fun SheetScaffold(
    title: String,
    bookTitle: String,
    page: Int,
    bodyText: String,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    hasPrevious: Boolean = true,
    hasNext: Boolean = true,
    onPrevious: () -> Unit = {},
    onNext: () -> Unit = {},
    testTag: String = "sheet_scaffold"
) {
    val extendedTokens = LocalExtendedDesignTokens.current
    val scrollState = rememberScrollState()

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .testTag(testTag)
            .clip(RoundedCornerShape(topStart = extendedTokens.sheetRadius, topEnd = extendedTokens.sheetRadius))
            .border(
                width = 1.dp,
                color = extendedTokens.hairlineBorderColor,
                shape = RoundedCornerShape(topStart = extendedTokens.sheetRadius, topEnd = extendedTokens.sheetRadius)
            ),
        color = MaterialTheme.colorScheme.surface
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            // Pinned Header
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.surface)
                    .padding(horizontal = DesignSpacing.space16, vertical = DesignSpacing.space12),
                verticalArrangement = Arrangement.spacedBy(DesignSpacing.space8)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontFamily = DesignFonts.ArabicUiFamily
                    )
                    IconButton(
                        onClick = onClose,
                        modifier = Modifier
                            .size(48.dp) // Touch target >= 48dp
                            .testTag("sheet_close")
                    ) {
                        Icon(
                            imageVector = Icons.Default.Close,
                            contentDescription = "إغلاق",
                            tint = MaterialTheme.colorScheme.onSurface
                        )
                    }
                }

                CitationLine(
                    bookTitle = bookTitle,
                    page = page,
                    testTag = "sheet_citation"
                )
            }

            HorizontalDivider(
                thickness = 1.dp,
                color = extendedTokens.hairlineBorderColor
            )

            // Scrollable Body
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 120.dp, max = 320.dp)
                    .verticalScroll(scrollState)
                    .padding(DesignSpacing.space16)
            ) {
                Text(
                    text = bodyText,
                    fontFamily = DesignFonts.EnglishBookPassageFamily,
                    style = MaterialTheme.typography.bodyLarge.copy(
                        fontSize = 15.sp,
                        lineHeight = 24.sp,
                        textDirection = TextDirection.Ltr
                    ),
                    color = MaterialTheme.colorScheme.onSurface
                )
            }

            HorizontalDivider(
                thickness = 1.dp,
                color = extendedTokens.hairlineBorderColor
            )

            // Pinned Footer with "السابق" and "التالي"
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.surface)
                    .padding(horizontal = DesignSpacing.space16, vertical = DesignSpacing.space12),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                OutlinedButton(
                    onClick = onPrevious,
                    enabled = hasPrevious,
                    modifier = Modifier
                        .heightIn(min = 48.dp) // Touch target >= 48dp
                        .testTag("sheet_prev")
                ) {
                    Text(
                        text = "السابق",
                        fontFamily = DesignFonts.ArabicUiFamily,
                        fontWeight = FontWeight.Bold
                    )
                }

                Button(
                    onClick = onNext,
                    enabled = hasNext,
                    modifier = Modifier
                        .heightIn(min = 48.dp) // Touch target >= 48dp
                        .testTag("sheet_next")
                ) {
                    Text(
                        text = "التالي",
                        fontFamily = DesignFonts.ArabicUiFamily,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }
    }
}
