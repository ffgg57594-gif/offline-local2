package com.medai.assistant.design.motion

import android.content.Context
import android.provider.Settings
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext

/**
 * Checks whether the system has disabled animations (Reduce Motion setting).
 */
fun isReduceMotionEnabled(context: Context): Boolean {
    return runCatching {
        val resolver = context.contentResolver
        val transition = Settings.Global.getFloat(resolver, Settings.Global.TRANSITION_ANIMATION_SCALE, 1f)
        val animator = Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f)
        transition == 0f || animator == 0f
    }.getOrDefault(false)
}

/**
 * Animated enter container for cards with a 60ms stagger per item and 220ms duration.
 * Automatically respects the system reduce-motion setting.
 */
@Composable
fun StaggeredCardEnter(
    index: Int,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    val context = LocalContext.current
    val reduceMotion = remember(context) { isReduceMotionEnabled(context) }

    if (reduceMotion) {
        content()
    } else {
        val delayMillis = (index * 60).coerceAtMost(360)
        val visibleState = remember {
            MutableTransitionState(false).apply { targetState = true }
        }

        AnimatedVisibility(
            visibleState = visibleState,
            modifier = modifier,
            enter = fadeIn(
                animationSpec = tween(
                    durationMillis = 220,
                    delayMillis = delayMillis,
                    easing = FastOutSlowInEasing
                )
            ) + slideInVertically(
                initialOffsetY = { 40 },
                animationSpec = tween(
                    durationMillis = 220,
                    delayMillis = delayMillis,
                    easing = FastOutSlowInEasing
                )
            )
        ) {
            content()
        }
    }
}
