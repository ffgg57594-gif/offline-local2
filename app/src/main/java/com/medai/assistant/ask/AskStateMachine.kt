package com.medai.assistant.ask

import com.medai.assistant.data.InstallState
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Deterministic state machine for the ask screen.
 *
 * It has no Android dependencies, so every transition can be exercised on the
 * JVM with fake engines and a test coroutine scope. The real engine switches to
 * a background dispatcher before touching ONNX/SQLite.
 */
class AskStateMachine(
    private val engine: AskEngine,
    private val scope: CoroutineScope,
    val refusalSentence: String = GATE_REFUSAL_SENTENCE
) {
    private val _state = MutableStateFlow<AskState>(AskState.Installing("", 0L, 0L))
    val state: StateFlow<AskState> = _state.asStateFlow()

    private var searchJob: Job? = null
    private var generation = 0

    fun onInstallState(installState: InstallState) {
        if (_state.value !is AskState.Installing) return
        _state.value = when (installState) {
            is InstallState.Idle -> AskState.Installing("", 0L, 0L)
            is InstallState.Copying -> AskState.Installing(
                installState.fileName,
                installState.doneBytes,
                installState.totalBytes
            )
            is InstallState.Ready -> return
            is InstallState.Failed -> AskState.Error(installState.message)
        }
    }

    fun onLoadingModel() {
        if (_state.value is AskState.Installing || _state.value is AskState.Error) {
            _state.value = AskState.LoadingModel
        }
    }

    fun onReady() {
        if (
            _state.value is AskState.Installing ||
            _state.value is AskState.LoadingModel ||
            _state.value is AskState.Error
        ) {
            _state.value = AskState.Ready
        }
    }

    fun onError(message: String) {
        // An in-flight search reports its own failure; do not overwrite it with
        // a late runtime error.
        if (_state.value !is AskState.Searching) {
            _state.value = AskState.Error(message)
        }
    }

    /**
     * Submit a question.
     *
     * - ignored while the model is not ready (Installing/LoadingModel);
     * - a repeated tap on the same question while it is running is ignored;
     * - a different question cancels the running request;
     * - the Error state may be retried.
     */
    fun ask(question: String, preset: String) {
        val text = question.trim()
        if (text.isEmpty()) return

        val current = _state.value
        val canAsk = current is AskState.Ready ||
            current is AskState.Searching ||
            current is AskState.Results ||
            current is AskState.Rejected ||
            current is AskState.Error
        if (!canAsk) return

        if (current is AskState.Searching &&
            current.question.trim().equals(text, ignoreCase = true)
        ) {
            return
        }

        searchJob?.cancel()
        val thisGeneration = ++generation
        _state.value = AskState.Searching(text)
        searchJob = scope.launch {
            try {
                val answer = engine.answer(text, preset)
                if (thisGeneration != generation) return@launch
                _state.value = if (answer.decision.accepted) {
                    AskState.Results(
                        question = text,
                        top3 = answer.top3,
                        decision = answer.decision,
                        timings = answer.timings,
                        stems = answer.stems
                    )
                } else {
                    AskState.Rejected(
                        question = text,
                        refusal = refusalSentence,
                        top3 = answer.top3,
                        decision = answer.decision,
                        timings = answer.timings,
                        stems = answer.stems
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Throwable) {
                if (thisGeneration == generation) {
                    _state.value = AskState.Error(
                        failure.message ?: failure.javaClass.simpleName
                    )
                }
            }
        }
    }

    /** Cancel the running search and return to the ready state. */
    fun cancel() {
        generation++
        searchJob?.cancel()
        searchJob = null
        if (_state.value is AskState.Searching) {
            _state.value = AskState.Ready
        }
    }
}
