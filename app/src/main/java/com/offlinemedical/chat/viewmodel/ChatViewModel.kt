package com.offlinemedical.chat.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.offlinemedical.chat.data.db.ChatDatabase
import com.offlinemedical.chat.retrieval.HybridRetriever
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class ChatViewModel(private val db: ChatDatabase, private val retriever: HybridRetriever) : ViewModel() {
    private val _messages = MutableStateFlow<List<String>>(emptyList())
    val messages: StateFlow<List<String>> = _messages

    fun send(q: String) {
        viewModelScope.launch {
            _messages.value = _messages.value + "You: $q"
            val r = retriever.search(q)
            val answer = r.chunks.firstOrNull()?.text ?: "هذه المعلومة غير مذكورة في الكتب الطبية المدمجة في التطبيق."
            _messages.value = _messages.value + "Bot: $answer"
        }
    }
}
