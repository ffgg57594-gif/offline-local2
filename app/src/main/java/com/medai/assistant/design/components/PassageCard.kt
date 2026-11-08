package com.medai.assistant.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.medai.assistant.R
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens

/**
 * Builds an [AnnotatedString] that highlights matched query keywords with marker style.
 */
fun buildMarkerHighlightedText(
    text: String,
    highlightWords: List<String>,
    highlightBg: Color,
    highlightFg: Color
): AnnotatedString {
    if (highlightWords.isEmpty()) return AnnotatedString(text)
    return buildAnnotatedString {
        append(text)
        val lowerText = text.lowercase()
        for (word in highlightWords) {
            val cleanWord = word.trim().lowercase()
            if (cleanWord.length < 2) continue
            var index = lowerText.indexOf(cleanWord)
            while (index >= 0) {
                addStyle(
                    style = SpanStyle(
                        background = highlightBg,
                        color = highlightFg,
                        fontWeight = FontWeight.Bold
                    ),
                    start = index,
                    end = index + cleanWord.length
                )
                index = lowerText.indexOf(cleanWord, index + cleanWord.length)
            }
        }
    }
}

/**
 * Distinctive book-excerpt card:
 * - Start edge margin rail in accent color
 * - Start edge bookmark tab with page number ("ص 261" with Western digits)
 * - Rank chip (#1, #2, #3)
 * - Serif passage text with marker-highlighted terms
 * - Inline "عرض المزيد" toggle
 * - Subtle divider
 * - Copy action button (>= 48 dp touch target)
 */
@Composable
fun PassageCard(
    passageText: String,
    bookTitle: String,
    page: Int,
    rank: Int,
    modifier: Modifier = Modifier,
    highlightWords: List<String> = emptyList(),
    initiallyExpanded: Boolean = false,
    onCitationClick: (() -> Unit)? = null,
    onCopy: (() -> Unit)? = null,
    testTag: String = "passage_card"
) {
    val extendedTokens = LocalExtendedDesignTokens.current
    var isExpanded by remember { mutableStateOf(initiallyExpanded) }

    val annotatedPassage = remember(passageText, highlightWords, extendedTokens) {
        buildMarkerHighlightedText(
            text = passageText,
            highlightWords = highlightWords,
            highlightBg = extendedTokens.markerHighlightBackground,
            highlightFg = extendedTokens.markerHighlightText
        )
    }

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
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(IntrinsicSize.Min)
        ) {
            // Margin rail along the start edge
            Box(
                modifier = Modifier
                    .width(4.dp)
                    .fillMaxHeight()
                    .background(extendedTokens.marginRailColor)
            )

            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(DesignSpacing.space16),
                verticalArrangement = Arrangement.spacedBy(DesignSpacing.space8)
            ) {
                // Header: Bookmark tab ("ص 261") + Citation line + Rank chip
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    // Bookmark tab on start edge
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(extendedTokens.chipRadius))
                            .background(extendedTokens.bookmarkTabBackground)
                            .then(
                                if (onCitationClick != null) {
                                    Modifier.clickable(onClick = onCitationClick)
                                } else {
                                    Modifier
                                }
                            )
                            .padding(horizontal = DesignSpacing.space8, vertical = DesignSpacing.space4)
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(DesignSpacing.space4)
                        ) {
                            Text(
                                text = "ص",
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold,
                                color = extendedTokens.bookmarkTabText,
                                fontFamily = DesignFonts.ArabicUiFamily
                            )
                            Text(
                                text = page.toString(), // Western digits inside chip
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold,
                                color = extendedTokens.bookmarkTabText
                            )
                        }
                    }

                    // Rank chip
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(extendedTokens.chipRadius))
                            .background(extendedTokens.rankChipBackground)
                            .padding(horizontal = DesignSpacing.space8, vertical = DesignSpacing.space4)
                    ) {
                        Text(
                            text = "#$rank",
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold,
                            color = extendedTokens.rankChipText
                        )
                    }
                }

                // Citation details
                CitationLine(
                    bookTitle = bookTitle,
                    page = page,
                    onClick = onCitationClick
                )

                // Subtle hairline divider
                HorizontalDivider(
                    thickness = 0.75.dp,
                    color = extendedTokens.subtleDividerColor
                )

                // English book passage text in serif typography
                Text(
                    text = annotatedPassage,
                    fontFamily = DesignFonts.EnglishBookPassageFamily,
                    style = MaterialTheme.typography.bodyLarge.copy(
                        fontSize = 15.sp,
                        lineHeight = 23.sp,
                        textDirection = TextDirection.Ltr
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = if (isExpanded) Int.MAX_VALUE else 5,
                    overflow = TextOverflow.Ellipsis
                )

                // Inline toggle and copy action footer
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    if (passageText.length > 220) {
                        Text(
                            text = if (isExpanded) "عرض أقل" else "عرض المزيد",
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier
                                .clickable { isExpanded = !isExpanded }
                                .padding(vertical = DesignSpacing.space4)
                        )
                    } else {
                        Spacer(modifier = Modifier.width(1.dp))
                    }

                    if (onCopy != null) {
                        IconButton(
                            onClick = onCopy,
                            modifier = Modifier
                                .size(48.dp) // Touch target >= 48dp
                                .testTag("copy_button_${rank}")
                        ) {
                            Icon(
                                painter = painterResource(id = R.drawable.ic_copy),
                                contentDescription = "نسخ المقطع",
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(20.dp)
                            )
                        }
                    }
                }
            }
        }
    }
}
