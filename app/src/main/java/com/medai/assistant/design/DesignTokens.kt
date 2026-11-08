package com.medai.assistant.design

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.medai.assistant.R

/**
 * Modular 4/8/12/16/24 dp spacing tokens.
 */
object DesignSpacing {
    val space4: Dp = 4.dp
    val space8: Dp = 8.dp
    val space12: Dp = 12.dp
    val space16: Dp = 16.dp
    val space24: Dp = 24.dp
}

/**
 * Offline bundled font families with open OFL licenses.
 */
object DesignFonts {
    val ArabicUiFamily: FontFamily = FontFamily(
        Font(R.font.ibm_plex_sans_arabic_regular, FontWeight.Normal),
        Font(R.font.ibm_plex_sans_arabic_medium, FontWeight.Medium),
        Font(R.font.ibm_plex_sans_arabic_bold, FontWeight.Bold)
    )

    val EnglishBookPassageFamily: FontFamily = FontFamily(
        Font(R.font.source_serif_4_regular, FontWeight.Normal),
        Font(R.font.source_serif_4_italic, FontWeight.Normal, FontStyle.Italic),
        Font(R.font.source_serif_4_bold, FontWeight.Bold)
    )
}

/**
 * Extended semantic tokens for the distinctive medical reference design.
 */
@Immutable
data class ExtendedDesignTokens(
    val marginRailColor: Color,
    val bookmarkTabBackground: Color,
    val bookmarkTabText: Color,
    val markerHighlightBackground: Color,
    val markerHighlightText: Color,
    val hairlineBorderColor: Color,
    val rankChipBackground: Color,
    val rankChipText: Color,
    val offlineBadgeBackground: Color,
    val offlineBadgeText: Color,
    val subtleDividerColor: Color,
    val bubbleBackground: Color,
    val bubbleText: Color,
    val cardRadius: Dp,
    val chipRadius: Dp,
    val sheetRadius: Dp
)

val LocalExtendedDesignTokens = staticCompositionLocalOf {
    DesignTokens.PaperInkLightExtended
}

object DesignTokens {

    // =========================================================================
    // Direction A: "ورق وحبر" (Paper & Ink)
    // =========================================================================

    val PaperInkLightColors: ColorScheme = lightColorScheme(
        primary = Color(0xFF0F5C5C),          // Deep scholarly teal
        onPrimary = Color(0xFFFFFFFF),
        primaryContainer = Color(0xFFD2E8E7),
        onPrimaryContainer = Color(0xFF063636),
        secondary = Color(0xFF424D53),        // Ink secondary
        onSecondary = Color(0xFFFFFFFF),
        secondaryContainer = Color(0xFFE2E9EC),
        onSecondaryContainer = Color(0xFF1B2024),
        background = Color(0xFFF7F4EE),       // Warm textbook paper
        onBackground = Color(0xFF1B2024),     // Ink text
        surface = Color(0xFFFAF8F3),          // Reading surface
        onSurface = Color(0xFF1B2024),
        surfaceVariant = Color(0xFFEFECE4),   // Paper card surface
        onSurfaceVariant = Color(0xFF424D53),
        outline = Color(0xFFD8D3C8),          // Hairline paper border
        outlineVariant = Color(0xFFE5E0D5),
        error = Color(0xFFBA3D2A),            // Terracotta refusal/alert
        onError = Color(0xFFFFFFFF),
        errorContainer = Color(0xFFFFDAD4),
        onErrorContainer = Color(0xFF410001)
    )

    val PaperInkLightExtended = ExtendedDesignTokens(
        marginRailColor = Color(0xFF0F5C5C),
        bookmarkTabBackground = Color(0xFFDDEBE9),
        bookmarkTabText = Color(0xFF0B4B4B),
        markerHighlightBackground = Color(0xFFF8E4B3), // Amber highlighter (approx #F2C14E tint)
        markerHighlightText = Color(0xFF1B2024),
        hairlineBorderColor = Color(0xFFD8D3C8),
        rankChipBackground = Color(0xFFE5E1D7),
        rankChipText = Color(0xFF384349),
        offlineBadgeBackground = Color(0xFFE6EFEF),
        offlineBadgeText = Color(0xFF0F5C5C),
        subtleDividerColor = Color(0xFFE5E0D5),
        bubbleBackground = Color(0xFFEAE6DC),
        bubbleText = Color(0xFF1B2024),
        cardRadius = 12.dp,
        chipRadius = 8.dp,
        sheetRadius = 16.dp
    )

    val PaperInkDarkColors: ColorScheme = darkColorScheme(
        primary = Color(0xFF62B8B8),          // Warm teal
        onPrimary = Color(0xFF003737),
        primaryContainer = Color(0xFF144D4D),
        onPrimaryContainer = Color(0xFFBDE8E8),
        secondary = Color(0xFFB8B3A7),
        onSecondary = Color(0xFF222526),
        secondaryContainer = Color(0xFF34383A),
        onSecondaryContainer = Color(0xFFF3EFE7),
        background = Color(0xFF1B1D1E),       // Warm charcoal, not pure black
        onBackground = Color(0xFFF3EFE7),
        surface = Color(0xFF232627),          // Warm dark card
        onSurface = Color(0xFFF3EFE7),
        surfaceVariant = Color(0xFF2B2E2F),
        onSurfaceVariant = Color(0xFFB8B3A7),
        outline = Color(0xFF434749),          // Hairline charcoal border
        outlineVariant = Color(0xFF323536),
        error = Color(0xFFFFB4A9),
        onError = Color(0xFF690005),
        errorContainer = Color(0xFF930006),
        onErrorContainer = Color(0xFFFFDAD4)
    )

    val PaperInkDarkExtended = ExtendedDesignTokens(
        marginRailColor = Color(0xFF62B8B8),
        bookmarkTabBackground = Color(0xFF194545),
        bookmarkTabText = Color(0xFFBDE8E8),
        markerHighlightBackground = Color(0xFF4E3E18), // Warm amber dark highlight
        markerHighlightText = Color(0xFFFFE8B3),
        hairlineBorderColor = Color(0xFF434749),
        rankChipBackground = Color(0xFF35393B),
        rankChipText = Color(0xFFD6D1C6),
        offlineBadgeBackground = Color(0xFF1A3D3D),
        offlineBadgeText = Color(0xFF88D9D9),
        subtleDividerColor = Color(0xFF35393B),
        bubbleBackground = Color(0xFF2E3234),
        bubbleText = Color(0xFFF3EFE7),
        cardRadius = 12.dp,
        chipRadius = 8.dp,
        sheetRadius = 16.dp
    )

    // =========================================================================
    // Direction B: "ليل سريري" (Clinical Night)
    // =========================================================================

    val ClinicalNightLightColors: ColorScheme = lightColorScheme(
        primary = Color(0xFF006A5E),          // Medical blue-green
        onPrimary = Color(0xFFFFFFFF),
        primaryContainer = Color(0xFF9EF2E2),
        onPrimaryContainer = Color(0xFF00201B),
        secondary = Color(0xFF3B4851),
        onSecondary = Color(0xFFFFFFFF),
        secondaryContainer = Color(0xFFDEE5EA),
        onSecondaryContainer = Color(0xFF0E161C),
        background = Color(0xFFF4F7F9),       // Cool near-white
        onBackground = Color(0xFF0E161C),     // Deep navy text
        surface = Color(0xFFFFFFFF),
        onSurface = Color(0xFF0E161C),
        surfaceVariant = Color(0xFFE9EFF3),   // Crisp light clinical card
        onSurfaceVariant = Color(0xFF3B4851),
        outline = Color(0xFFCCD6DC),          // Crisp 1px divider
        outlineVariant = Color(0xFFD9E2E7),
        error = Color(0xFFBA3826),            // Clinical coral alert
        onError = Color(0xFFFFFFFF),
        errorContainer = Color(0xFFFFDAD4),
        onErrorContainer = Color(0xFF410001)
    )

    val ClinicalNightLightExtended = ExtendedDesignTokens(
        marginRailColor = Color(0xFF006A5E),
        bookmarkTabBackground = Color(0xFFD3EEF1),
        bookmarkTabText = Color(0xFF004953),
        markerHighlightBackground = Color(0xFFC9EFE8), // Medical cyan-green marker
        markerHighlightText = Color(0xFF003730),
        hairlineBorderColor = Color(0xFFCCD6DC),
        rankChipBackground = Color(0xFFDCE4E9),
        rankChipText = Color(0xFF28343C),
        offlineBadgeBackground = Color(0xFFE1F5F2),
        offlineBadgeText = Color(0xFF006A5E),
        subtleDividerColor = Color(0xFFD9E2E7),
        bubbleBackground = Color(0xFFE3EAEE),
        bubbleText = Color(0xFF0E161C),
        cardRadius = 8.dp,                    // Tighter clinical radii
        chipRadius = 4.dp,
        sheetRadius = 12.dp
    )

    val ClinicalNightDarkColors: ColorScheme = darkColorScheme(
        primary = Color(0xFF53DBC7),          // Clinical cyan-teal
        onPrimary = Color(0xFF003730),
        primaryContainer = Color(0xFF005047),
        onPrimaryContainer = Color(0xFF73F8E3),
        secondary = Color(0xFF9EADB7),
        onSecondary = Color(0xFF172025),
        secondaryContainer = Color(0xFF28343C),
        onSecondaryContainer = Color(0xFFEEF3F6),
        background = Color(0xFF0E1417),       // Deep ink-navy dark
        onBackground = Color(0xFFEEF3F6),
        surface = Color(0xFF131A1E),
        onSurface = Color(0xFFEEF3F6),
        surfaceVariant = Color(0xFF1B2328),   // Deep navy card
        onSurfaceVariant = Color(0xFF9EADB7),
        outline = Color(0xFF333E46),          // Crisp 1px divider
        outlineVariant = Color(0xFF263037),
        error = Color(0xFFFFB4A9),            // Coral alert
        onError = Color(0xFF690005),
        errorContainer = Color(0xFF930006),
        onErrorContainer = Color(0xFFFFDAD4)
    )

    val ClinicalNightDarkExtended = ExtendedDesignTokens(
        marginRailColor = Color(0xFF53DBC7),
        bookmarkTabBackground = Color(0xFF103E48),
        bookmarkTabText = Color(0xFFA3E5F3),
        markerHighlightBackground = Color(0xFF0F4640),
        markerHighlightText = Color(0xFFA2F5E7),
        hairlineBorderColor = Color(0xFF333E46),
        rankChipBackground = Color(0xFF28343C),
        rankChipText = Color(0xFFD6E3EA),
        offlineBadgeBackground = Color(0xFF0D332E),
        offlineBadgeText = Color(0xFF64ECD6),
        subtleDividerColor = Color(0xFF263037),
        bubbleBackground = Color(0xFF1E282E),
        bubbleText = Color(0xFFEEF3F6),
        cardRadius = 8.dp,
        chipRadius = 4.dp,
        sheetRadius = 12.dp
    )

    /**
     * Typography configuration applying IBM Plex Sans Arabic to UI elements.
     */
    fun createTypography(): Typography {
        val base = DesignFonts.ArabicUiFamily
        return Typography(
            headlineLarge = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Bold,
                fontSize = 26.sp,
                lineHeight = 34.sp
            ),
            headlineMedium = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Bold,
                fontSize = 22.sp,
                lineHeight = 30.sp
            ),
            titleLarge = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Bold,
                fontSize = 19.sp,
                lineHeight = 26.sp
            ),
            titleMedium = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Medium,
                fontSize = 16.sp,
                lineHeight = 22.sp
            ),
            titleSmall = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Medium,
                fontSize = 14.sp,
                lineHeight = 20.sp
            ),
            bodyLarge = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Normal,
                fontSize = 16.sp,
                lineHeight = 24.sp
            ),
            bodyMedium = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Normal,
                fontSize = 14.sp,
                lineHeight = 20.sp
            ),
            bodySmall = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Normal,
                fontSize = 12.sp,
                lineHeight = 16.sp
            ),
            labelLarge = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Medium,
                fontSize = 14.sp,
                lineHeight = 18.sp
            ),
            labelMedium = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Medium,
                fontSize = 12.sp,
                lineHeight = 16.sp
            ),
            labelSmall = TextStyle(
                fontFamily = base,
                fontWeight = FontWeight.Medium,
                fontSize = 11.sp,
                lineHeight = 14.sp
            )
        )
    }

    fun createShapes(direction: DesignDirection): Shapes {
        return if (direction == DesignDirection.PAPER_INK) {
            Shapes(
                extraSmall = RoundedCornerShape(4.dp),
                small = RoundedCornerShape(6.dp),
                medium = RoundedCornerShape(12.dp),
                large = RoundedCornerShape(16.dp),
                extraLarge = RoundedCornerShape(24.dp)
            )
        } else {
            Shapes(
                extraSmall = RoundedCornerShape(2.dp),
                small = RoundedCornerShape(4.dp),
                medium = RoundedCornerShape(8.dp),
                large = RoundedCornerShape(12.dp),
                extraLarge = RoundedCornerShape(20.dp)
            )
        }
    }
}

/**
 * Top-level theme composable for applying the selected DesignDirection and theme variant.
 */
@Composable
fun MedAiDesignTheme(
    direction: DesignDirection = DesignConfig.activeDirection,
    darkTheme: Boolean = false,
    content: @Composable () -> Unit
) {
    val (colorScheme, extendedTokens) = when (direction) {
        DesignDirection.PAPER_INK -> {
            if (darkTheme) {
                DesignTokens.PaperInkDarkColors to DesignTokens.PaperInkDarkExtended
            } else {
                DesignTokens.PaperInkLightColors to DesignTokens.PaperInkLightExtended
            }
        }
        DesignDirection.CLINICAL_NIGHT -> {
            if (darkTheme) {
                DesignTokens.ClinicalNightDarkColors to DesignTokens.ClinicalNightDarkExtended
            } else {
                DesignTokens.ClinicalNightLightColors to DesignTokens.ClinicalNightLightExtended
            }
        }
    }

    val typography = DesignTokens.createTypography()
    val shapes = DesignTokens.createShapes(direction)

    CompositionLocalProvider(
        LocalExtendedDesignTokens provides extendedTokens
    ) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = typography,
            shapes = shapes,
            content = content
        )
    }
}
