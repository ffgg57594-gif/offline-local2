package com.medai.assistant.ask

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.medai.assistant.SearchTiming
import com.medai.assistant.data.Chunk
import com.medai.assistant.diagnostics.Diagnostics
import com.medai.assistant.runtime.AppGraph
import com.medai.assistant.runtime.AppRuntimeState
import com.medai.assistant.runtime.LoadedResources
import com.medai.assistant.settings.AppSettings
import com.medai.assistant.settings.SettingsRepository
import com.medai.assistant.settings.settingsDataStore
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * Owns the ask state machine and wires it to the process-wide AppGraph.
 *
 * A ViewModel survives rotation, and AppGraph keeps the ONNX session,
 * tokenizer, embedding matrix and gate database for the whole process, so a
 * rotation never reloads them.
 */
class AskViewModel(application: Application) : AndroidViewModel(application) {

    private val settingsRepository =
        SettingsRepository(application.settingsDataStore)

    val settings: StateFlow<AppSettings> = settingsRepository.settings.stateIn(
        scope = viewModelScope,
        started = SharingStarted.Eagerly,
        initialValue = AppSettings()
    )

    private val machine = AskStateMachine(
        engine = AppGraphEngine(),
        scope = viewModelScope,
        refusalSentence = GATE_REFUSAL_SENTENCE
    )

    val state: StateFlow<AskState> = machine.state

    init {
        AppGraph.start(application)
        viewModelScope.launch {
            AppGraph.installState.collect { machine.onInstallState(it) }
        }
        viewModelScope.launch {
            AppGraph.runtimeState.collect { runtime ->
                when (runtime) {
                    is AppRuntimeState.Idle -> Unit
                    is AppRuntimeState.Installing -> Unit
                    is AppRuntimeState.LoadingModel -> machine.onLoadingModel()
                    is AppRuntimeState.Ready -> machine.onReady()
                    is AppRuntimeState.Failed -> machine.onError(runtime.message)
                }
            }
        }
    }

    fun ask(question: String) {
        machine.ask(question, settings.value.preset)
    }

    fun cancel() {
        machine.cancel()
    }

    fun setPreset(preset: String) {
        viewModelScope.launch { settingsRepository.setPreset(preset) }
    }

    fun setShowTimings(show: Boolean) {
        viewModelScope.launch { settingsRepository.setShowTimings(show) }
    }

    suspend fun neighbour(chunkId: Int, delta: Int): Passage? {
        val chunk = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            AppGraph.requireResources().repository.getNeighbour(chunkId, delta)
        } ?: return null
        return chunk.toPassage(rank = 0)
    }

    private fun Chunk.toPassage(rank: Int): Passage = Passage(
        chunkId = id,
        rank = rank,
        bookName = bookName,
        page = page,
        section = section,
        text = text
    )

    private inner class AppGraphEngine : AskEngine {
        override suspend fun answer(question: String, preset: String): AskAnswer {
            Diagnostics.searchCount += 1
            val resources = AppGraph.requireResources()
            val answer = resources.toEngine().answer(question, preset)
            Diagnostics.recordTimings(
                question,
                SearchTiming(
                    tokenizeMs = answer.timings.tokenizeMs,
                    embedMs = answer.timings.embedMs,
                    searchMs = answer.timings.searchMs,
                    totalMs = answer.timings.totalMs,
                    gateSignalsMs = answer.timings.gateSignalsMs
                )
            )
            return answer
        }

        override suspend fun neighbour(chunkId: Int, delta: Int): Chunk? {
            return AppGraph.requireResources().repository.getNeighbour(chunkId, delta)
        }
    }

    private fun LoadedResources.toEngine(): DeviceAskEngine {
        val vocab = gateVocab ?: error(
            "فلتر الرفض غير مهيأ: ${gateInitError ?: "gate_vocab.json"}"
        )
        val config = gateConfig ?: error(
            "فلتر الرفض غير مهيأ: ${gateInitError ?: "gate_config.json"}"
        )
        val database = gateDatabase ?: error(
            "فلتر الرفض غير مهيأ: ${gateInitError ?: "books_knowledge.db FTS5"}"
        )
        return DeviceAskEngine(
            repository = repository,
            tokenizer = tokenizer,
            embedder = embedder,
            denseSearch = denseSearch,
            gateVocab = vocab,
            gateConfig = config,
            gateDatabase = database
        )
    }
}
