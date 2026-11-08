package com.medai.assistant.design.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens

/**
 * Determinate progress card for the one-time asset installation.
 */
@Composable
fun AssetInstallProgress(
    fileName: String,
    doneBytes: Long,
    totalBytes: Long,
    modifier: Modifier = Modifier,
    testTag: String = "install_progress"
) {
    val extendedTokens = LocalExtendedDesignTokens.current
    val fraction = if (totalBytes > 0) {
        (doneBytes.toFloat() / totalBytes.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val percentage = (fraction * 100).toInt()

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
        Column(verticalArrangement = Arrangement.spacedBy(DesignSpacing.space8)) {
            Text(
                text = "تجهيز المرجع الطبي",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontFamily = DesignFonts.ArabicUiFamily
            )
            Text(
                text = "يتم فك ونسخ ملفات المعرفة والمحاذاة مرة واحدة فقط.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontFamily = DesignFonts.ArabicUiFamily
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
                    text = "$fileName — $percentage%",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = "$doneBytes / $totalBytes بايت",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

/**
 * Inline searching state with a small spinner and "جارٍ البحث…".
 */
@Composable
fun SearchingInlineProgress(
    modifier: Modifier = Modifier,
    message: String = "جارٍ البحث في الكتاب المدمج…",
    testTag: String = "searching_progress"
) {
    val extendedTokens = LocalExtendedDesignTokens.current

    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp) // Touch / target container >= 48dp
            .testTag(testTag)
            .clip(RoundedCornerShape(extendedTokens.cardRadius))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            .border(
                width = 1.dp,
                color = extendedTokens.hairlineBorderColor,
                shape = RoundedCornerShape(extendedTokens.cardRadius)
            )
            .padding(horizontal = DesignSpacing.space16, vertical = DesignSpacing.space12),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(DesignSpacing.space12)
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(20.dp),
            strokeWidth = 2.5.dp,
            color = MaterialTheme.colorScheme.primary
        )
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontFamily = DesignFonts.ArabicUiFamily
        )
    }
}

/**
 * Shimmer skeleton placeholder simulating a result passage card while vectors load.
 */
@Composable
fun ShimmerResultCardSkeleton(
    modifier: Modifier = Modifier,
    testTag: String = "shimmer_skeleton"
) {
    val extendedTokens = LocalExtendedDesignTokens.current

    val transition = rememberInfiniteTransition(label = "shimmer")
    val translateAnim by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1000f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1200, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "shimmer_translation"
    )

    val baseColor = MaterialTheme.colorScheme.surfaceVariant
    val highlightColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.6f)
    val shimmerBrush = Brush.linearGradient(
        colors = listOf(baseColor, highlightColor, baseColor),
        start = Offset(translateAnim - 200f, 0f),
        end = Offset(translateAnim + 200f, 200f)
    )

    Box(
        modifier = modifier
            .fillMaxWidth()
            .testTag(testTag)
            .clip(RoundedCornerShape(extendedTokens.cardRadius))
            .background(baseColor)
            .border(
                width = 1.dp,
                color = extendedTokens.hairlineBorderColor,
                shape = RoundedCornerShape(extendedTokens.cardRadius)
            )
            .padding(DesignSpacing.space16)
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(DesignSpacing.space12)) {
            // Header placeholders
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Box(
                    modifier = Modifier
                        .size(width = 80.dp, height = 20.dp)
                        .clip(RoundedCornerShape(extendedTokens.chipRadius))
                        .background(shimmerBrush)
                )
                Box(
                    modifier = Modifier
                        .size(width = 32.dp, height = 20.dp)
                        .clip(RoundedCornerShape(extendedTokens.chipRadius))
                        .background(shimmerBrush)
                )
            }

            // Text line placeholders
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(14.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(shimmerBrush)
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth(0.92f)
                    .height(14.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(shimmerBrush)
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth(0.75f)
                    .height(14.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(shimmerBrush)
            )
        }
    }
}
