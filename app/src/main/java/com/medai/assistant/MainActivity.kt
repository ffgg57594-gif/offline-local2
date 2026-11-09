package com.medai.assistant

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.lifecycle.ViewModelProvider
import com.medai.assistant.ask.AskViewModel
import com.medai.assistant.design.DesignConfig
import com.medai.assistant.design.MedAiDesignTheme
import com.medai.assistant.ui.AskScreen
import com.medai.assistant.ui.DebugScreen
import com.medai.assistant.ui.UiOverrides

class MainActivity : ComponentActivity() {

    private val askViewModel: AskViewModel by lazy {
        ViewModelProvider(this)[AskViewModel::class.java]
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            val dark = UiOverrides.forceDark ?: isSystemInDarkTheme()
            val systemDensity = LocalDensity.current
            val density = UiOverrides.fontScale?.let { scale ->
                Density(systemDensity.density, scale)
            } ?: systemDensity

            MedAiDesignTheme(
                direction = DesignConfig.activeDirection,
                darkTheme = dark
            ) {
                CompositionLocalProvider(
                    LocalLayoutDirection provides LayoutDirection.Rtl,
                    LocalDensity provides density
                ) {
                    var showDebug by rememberSaveable { mutableStateOf(false) }
                    if (showDebug) {
                        DebugScreen(onBack = { showDebug = false })
                    } else {
                        AskScreen(
                            viewModel = askViewModel,
                            onOpenDebug = { showDebug = true }
                        )
                    }
                }
            }
        }
    }
}
