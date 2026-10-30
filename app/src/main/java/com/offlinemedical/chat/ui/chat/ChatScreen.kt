package com.offlinemedical.chat.ui.chat

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

import androidx.compose.material3.ExperimentalMaterial3Api

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(onOpenSettings: () -> Unit) {
    var text by remember { mutableStateOf("") }
    Scaffold(
        topBar = {
            TopAppBar(title = { Text("Offline Strict Medical Textbooks Chat") }, actions = {
                IconButton(onClick = onOpenSettings) { Text("⚙") }
            })
        }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            Text("Book Answer mode: answers come verbatim from baked-in textbooks.", Modifier.padding(16.dp))
            Spacer(Modifier.weight(1f))
            Row(Modifier.padding(8.dp)) {
                OutlinedTextField(value = text, onValueChange = { text = it }, modifier = Modifier.weight(1f))
                Button(onClick = { }) { Text("Send") }
            }
        }
    }
}
