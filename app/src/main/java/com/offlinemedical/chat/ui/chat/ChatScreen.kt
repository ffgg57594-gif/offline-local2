package com.offlinemedical.chat.ui.chat

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(onOpenSettings: () -> Unit) {
    var text by remember { mutableStateOf("") }
    var messages by remember { mutableStateOf(listOf<MessageUi>()) }
    val listState = rememberLazyListState()
    var showDrawer by remember { mutableStateOf(false) }

    ModalNavigationDrawer(
        drawerState = rememberDrawerState(if (showDrawer) DrawerValue.Open else DrawerValue.Closed),
        drawerContent = {
            ModalDrawerSheet {
                Text("Conversations", modifier = Modifier.padding(16.dp), style = MaterialTheme.typography.titleMedium)
                NavigationDrawerItem(label = { Text("New chat") }, selected = false, onClick = { messages = emptyList() })
            }
        }
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("Offline Medical Chat") },
                    navigationIcon = { IconButton(onClick = { showDrawer = !showDrawer }) { Icon(Icons.Default.Menu, "menu") } },
                    actions = { IconButton(onClick = onOpenSettings) { Text("⚙") } }
                )
            }
        ) { padding ->
            Column(Modifier.padding(padding).fillMaxSize()) {
                if (messages.isEmpty()) {
                    EmptyState(Modifier.weight(1f))
                } else {
                    LazyColumn(state = listState, modifier = Modifier.weight(1f).padding(horizontal = 8.dp)) {
                        items(messages) { m -> MessageBubble(m) }
                    }
                }
                Composer(
                    text = text,
                    onTextChange = { text = it },
                    onSend = {
                        if (text.isNotBlank()) {
                            messages = messages + MessageUi(text, true)
                            messages = messages + MessageUi("Book Answer: (retrieval pending)", false)
                            text = ""
                        }
                    }
                )
            }
        }
    }
}

@Composable
fun EmptyState(modifier: Modifier = Modifier) {
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Text("Offline Strict Medical Textbooks Chat", style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
        Spacer(Modifier.height(8.dp))
        Text("Ask a question. Answers come verbatim from baked-in textbooks.", style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
        Spacer(Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SuggestionChip(onClick = {}, label = { Text("What is hypertension?") })
            SuggestionChip(onClick = {}, label = { Text("Dosage of amoxicillin") })
        }
    }
}

@Composable
fun MessageBubble(m: MessageUi) {
    val align = if (m.isUser) Arrangement.End else Arrangement.Start
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = align) {
        Card(
            colors = CardDefaults.cardColors(
                containerColor = if (m.isUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant
            ),
            modifier = Modifier.widthIn(max = 320.dp)
        ) {
            Column(Modifier.padding(12.dp)) {
                Text(m.text, style = MaterialTheme.typography.bodyLarge)
                if (!m.isUser) {
                    Spacer(Modifier.height(4.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        AssistChip(onClick = {}, label = { Text("Explain") })
                        AssistChip(onClick = {}, label = { Text("[المصدر: book - صفحة 1]") })
                    }
                }
            }
        }
    }
}

@Composable
fun Composer(text: String, onTextChange: (String) -> Unit, onSend: () -> Unit) {
    Surface(tonalElevation = 2.dp) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.Bottom) {
            IconButton(onClick = {}) { Icon(Icons.Default.Add, "attach") }
            OutlinedTextField(
                value = text, onValueChange = onTextChange,
                modifier = Modifier.weight(1f),
                placeholder = { Text("Message...") },
                maxLines = 5
            )
            IconButton(onClick = onSend) { Icon(Icons.Default.Send, "send") }
        }
    }
}

data class MessageUi(val text: String, val isUser: Boolean)
