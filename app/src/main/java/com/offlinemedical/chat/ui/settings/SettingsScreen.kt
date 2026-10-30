package com.offlinemedical.chat.ui.settings

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun SettingsScreen(onBack: () -> Unit) {
    Scaffold(topBar = {
        TopAppBar(title = { Text("Settings") }, navigationIcon = { IconButton(onClick = onBack) { Text("←") } })
    }) { padding ->
        Column(Modifier.padding(padding).padding(16.dp)) {
            Text("Model Manager, threshold slider, theme, text size, clear history.")
        }
    }
}
