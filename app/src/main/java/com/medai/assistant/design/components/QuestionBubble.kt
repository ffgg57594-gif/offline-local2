package com.medai.assistant.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.dp
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens

/**
 * Question bubble aligned to the start side with direction automatically detected from the text.
 */
@Composable
fun QuestionBubble(
    question: String,
    modifier: Modifier = Modifier,
    testTag: String = "question_bubble"
) {
    val extendedTokens = LocalExtendedDesignTokens.current
    val hasArabic = question.any { it in '\u0600'..'\u06FF' }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .testTag(testTag),
        contentAlignment = Alignment.CenterStart
    ) {
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(extendedTokens.cardRadius))
                .background(extendedTokens.bubbleBackground)
                .border(
                    width = 1.dp,
                    color = extendedTokens.hairlineBorderColor,
                    shape = RoundedCornerShape(extendedTokens.cardRadius)
                )
                .padding(horizontal = DesignSpacing.space16, vertical = DesignSpacing.space12)
        ) {
            Text(
                text = question,
                style = MaterialTheme.typography.bodyLarge.copy(
                    fontFamily = if (hasArabic) DesignFonts.ArabicUiFamily else null,
                    textDirection = if (hasArabic) TextDirection.Rtl else TextDirection.Ltr,
                    textAlign = if (hasArabic) TextAlign.Right else TextAlign.Left
                ),
                color = extendedTokens.bubbleText,
                fontWeight = FontWeight.Medium
            )
        }
    }
}
