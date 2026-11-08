package com.medai.assistant.design.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens

/**
 * Line-art illustration drawn exclusively with Compose Canvas (open book + magnifier).
 */
@Composable
fun BookMagnifierIllustration(
    color: Color,
    modifier: Modifier = Modifier
) {
    Canvas(
        modifier = modifier
            .size(120.dp, 80.dp)
            .testTag("empty_state_canvas")
    ) {
        val w = size.width
        val h = size.height
        val strokeWidth = 2.5f

        // Spine center
        val centerX = w * 0.45f
        val baseY = h * 0.75f
        val topY = h * 0.25f

        // Left page curve
        val leftPath = Path().apply {
            moveTo(centerX, topY + 10f)
            cubicTo(
                centerX - w * 0.15f, topY,
                centerX - w * 0.35f, topY - 5f,
                w * 0.05f, topY + 8f
            )
            lineTo(w * 0.05f, baseY + 8f)
            cubicTo(
                centerX - w * 0.35f, baseY - 5f,
                centerX - w * 0.15f, baseY,
                centerX, baseY + 10f
            )
            close()
        }
        drawPath(
            path = leftPath,
            color = color,
            style = Stroke(width = strokeWidth, cap = StrokeCap.Round, join = StrokeJoin.Round)
        )

        // Right page curve
        val rightPath = Path().apply {
            moveTo(centerX, topY + 10f)
            cubicTo(
                centerX + w * 0.15f, topY,
                centerX + w * 0.35f, topY - 5f,
                w * 0.85f, topY + 8f
            )
            lineTo(w * 0.85f, baseY + 8f)
            cubicTo(
                centerX + w * 0.35f, baseY - 5f,
                centerX + w * 0.15f, baseY,
                centerX, baseY + 10f
            )
            close()
        }
        drawPath(
            path = rightPath,
            color = color,
            style = Stroke(width = strokeWidth, cap = StrokeCap.Round, join = StrokeJoin.Round)
        )

        // Book lines (left page text suggestion)
        drawLine(
            color = color.copy(alpha = 0.5f),
            start = Offset(w * 0.12f, topY + 22f),
            end = Offset(centerX - w * 0.08f, topY + 22f),
            strokeWidth = 1.5f,
            cap = StrokeCap.Round
        )
        drawLine(
            color = color.copy(alpha = 0.5f),
            start = Offset(w * 0.12f, topY + 36f),
            end = Offset(centerX - w * 0.08f, topY + 36f),
            strokeWidth = 1.5f,
            cap = StrokeCap.Round
        )

        // Magnifier lens over right page
        val lensCenterX = w * 0.65f
        val lensCenterY = h * 0.45f
        val lensRadius = w * 0.18f

        drawCircle(
            color = color,
            radius = lensRadius,
            center = Offset(lensCenterX, lensCenterY),
            style = Stroke(width = strokeWidth * 1.2f)
        )

        // Magnifier handle
        val handleStart = Offset(
            lensCenterX + lensRadius * 0.707f,
            lensCenterY + lensRadius * 0.707f
        )
        val handleEnd = Offset(
            handleStart.x + w * 0.18f,
            handleStart.y + h * 0.22f
        )
        drawLine(
            color = color,
            start = handleStart,
            end = handleEnd,
            strokeWidth = strokeWidth * 1.8f,
            cap = StrokeCap.Round
        )
    }
}

data class ExampleQuestionItem(
    val question: String,
    val icon: ImageVector,
    val iconDescription: String
)

/**
 * EmptyState composable according to STAGE UI-A item 4:
 * Line-art illustration with Canvas (no bitmap files), short Arabic title,
 * one explanatory line, and 4 example cards with icons.
 */
@Composable
fun EmptyState(
    modifier: Modifier = Modifier,
    title: String = "اسأل عن كتابك الطبي",
    subtitle: String = "الإجابات من الكتاب المدمج فقط، دون اتصال بالإنترنت.",
    examples: List<ExampleQuestionItem> = listOf(
        ExampleQuestionItem("What causes bacterial vaginosis?", Icons.Filled.Search, "بحث عن السبب"),
        ExampleQuestionItem("When is the best time to insert an IUD?", Icons.Filled.DateRange, "توقيت الإجراء"),
        ExampleQuestionItem("What are the potential complications of IUD use?", Icons.Filled.Warning, "تنبيه المضاعفات"),
        ExampleQuestionItem("What options are available for emergency contraception?", Icons.Filled.FavoriteBorder, "خيارات الطوارئ")
    ),
    onExampleClick: (String) -> Unit = {}
) {
    val extendedTokens = LocalExtendedDesignTokens.current

    Column(
        modifier = modifier
            .fillMaxWidth()
            .testTag("empty_state_container"),
        verticalArrangement = Arrangement.spacedBy(DesignSpacing.space16)
    ) {
        // Line-art canvas illustration
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = DesignSpacing.space8),
            contentAlignment = Alignment.Center
        ) {
            BookMagnifierIllustration(
                color = MaterialTheme.colorScheme.primary
            )
        }

        // Title & single explanatory line
        Column(verticalArrangement = Arrangement.spacedBy(DesignSpacing.space4)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
                fontFamily = DesignFonts.ArabicUiFamily
            )
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontFamily = DesignFonts.ArabicUiFamily
            )
        }

        Text(
            text = "أسئلة استرشادية",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onBackground,
            fontFamily = DesignFonts.ArabicUiFamily
        )

        // 4 example cards with icons
        Column(verticalArrangement = Arrangement.spacedBy(DesignSpacing.space8)) {
            examples.forEachIndexed { index, item ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp) // Touch target >= 48dp
                        .testTag("example_card_$index")
                        .clip(RoundedCornerShape(extendedTokens.cardRadius))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .border(
                            width = 1.dp,
                            color = extendedTokens.hairlineBorderColor,
                            shape = RoundedCornerShape(extendedTokens.cardRadius)
                        )
                        .clickable(role = Role.Button) { onExampleClick(item.question) }
                        .padding(horizontal = DesignSpacing.space16, vertical = DesignSpacing.space12),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = item.question,
                        style = MaterialTheme.typography.bodyMedium.copy(
                            textDirection = androidx.compose.ui.text.style.TextDirection.Content
                        ),
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f)
                    )
                    Icon(
                        imageVector = item.icon,
                        contentDescription = item.iconDescription,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .padding(start = DesignSpacing.space8)
                            .size(20.dp)
                    )
                }
            }
        }
    }
}
