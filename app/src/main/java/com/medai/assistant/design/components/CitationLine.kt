package com.medai.assistant.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.medai.assistant.design.DesignFonts
import com.medai.assistant.design.DesignSpacing
import com.medai.assistant.design.LocalExtendedDesignTokens

/**
 * Explicit bidi citation line: renders separate Texts for Arabic and English portions.
 * Reads from the right in RTL: "المصدر:" bookTitle "· صفحة 261" (Western digits).
 */
@Composable
fun CitationLine(
    bookTitle: String,
    page: Int,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    testTag: String = "citation_line"
) {
    val extendedTokens = LocalExtendedDesignTokens.current

    val containerModifier = modifier
        .testTag(testTag)
        .clip(RoundedCornerShape(extendedTokens.chipRadius))
        .background(extendedTokens.bookmarkTabBackground)
        .border(
            width = 1.dp,
            color = extendedTokens.hairlineBorderColor,
            shape = RoundedCornerShape(extendedTokens.chipRadius)
        )
        .then(
            if (onClick != null) {
                Modifier.clickable(role = Role.Button, onClick = onClick)
            } else {
                Modifier
            }
        )
        .padding(horizontal = DesignSpacing.space8, vertical = DesignSpacing.space4)

    Row(
        modifier = containerModifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(DesignSpacing.space4)
    ) {
        Text(
            text = "المصدر:",
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = extendedTokens.bookmarkTabText,
            fontFamily = DesignFonts.ArabicUiFamily
        )
        Text(
            text = bookTitle,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Medium,
            color = extendedTokens.bookmarkTabText
        )
        Text(
            text = "·",
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = extendedTokens.bookmarkTabText
        )
        Text(
            text = "صفحة",
            style = MaterialTheme.typography.labelSmall,
            color = extendedTokens.bookmarkTabText,
            fontFamily = DesignFonts.ArabicUiFamily
        )
        Text(
            text = page.toString(), // Western digits
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = extendedTokens.bookmarkTabText
        )
    }
}
