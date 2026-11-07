package com.medai.assistant.ask

import com.medai.assistant.data.Chunk
import com.medai.assistant.data.InstallState
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class AskStateMachineTest {

    private fun passage(id: Int = 1): Passage = Passage(
        chunkId = id,
        rank = 1,
        bookName = "book_one",
        page = 7,
        section = "section",
        text = "passage text",
        highlightRanges = emptyList()
    )

    private fun answer(question: String, accepted: Boolean = true): AskAnswer = AskAnswer(
        question = question,
        top3 = listOf(passage()),
        decision = AskDecision(
            accepted = accepted,
            preset = "balanced",
            s1 = 0.9,
            s3 = 1.0,
            s4 = 0,
            gateAvailable = true,
            gateError = null
        ),
        timings = AskTiming(tokenizeMs = 1, embedMs = 2, searchMs = 3, totalMs = 6),
        stems = listOf("test")
    )

    private class FakeEngine(
        var auto: ((String) -> AskAnswer)? = null
    ) : AskEngine {
        val calls = mutableListOf<Pair<String, String>>()
        val gates = ArrayDeque<CompletableDeferred<AskAnswer>>()

        override suspend fun answer(question: String, preset: String): AskAnswer {
            calls.add(question to preset)
            val autoAnswer = auto
            if (autoAnswer != null) return autoAnswer(question)
            val gate = CompletableDeferred<AskAnswer>()
            gates.addLast(gate)
            return gate.await()
        }

        override suspend fun neighbour(chunkId: Int, delta: Int): Chunk? = null
    }

    @Test
    fun installProgressThenLoadingThenReady() = runTest {
        val machine = AskStateMachine(FakeEngine(), this)

        assertTrue(machine.state.value is AskState.Installing)

        machine.onInstallState(InstallState.Copying("embeddings.bin", 25L, 100L))
        val copying = machine.state.value as AskState.Installing
        assertEquals("embeddings.bin", copying.fileName)
        assertEquals(25L, copying.doneBytes)
        assertEquals(100L, copying.totalBytes)

        machine.onInstallState(InstallState.Ready(File("/tmp")))
        assertTrue(machine.state.value is AskState.Installing)

        machine.onLoadingModel()
        assertTrue(machine.state.value is AskState.LoadingModel)

        machine.onReady()
        assertTrue(machine.state.value is AskState.Ready)
    }

    @Test
    fun installFailureShowsError() = runTest {
        val machine = AskStateMachine(FakeEngine(), this)
        machine.onInstallState(InstallState.Failed("disk full"))
        val error = machine.state.value as AskState.Error
        assertEquals("disk full", error.message)
    }

    @Test
    fun askIsIgnoredWhileModelIsNotReady() = runTest {
        val engine = FakeEngine()
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()

        machine.ask("What causes bacterial vaginosis?", "balanced")
        advanceUntilIdle()

        assertTrue(machine.state.value is AskState.LoadingModel)
        assertTrue(engine.calls.isEmpty())
    }

    @Test
    fun askShowsSearchingThenResults() = runTest {
        val engine = FakeEngine { question -> answer(question, accepted = true) }
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("What causes bacterial vaginosis?", "balanced")
        advanceUntilIdle()

        val results = machine.state.value as AskState.Results
        assertEquals("What causes bacterial vaginosis?", results.question)
        assertEquals(1, results.top3.size)
        assertTrue(results.decision.accepted)
        assertEquals(listOf("What causes bacterial vaginosis?" to "balanced"), engine.calls)
    }

    @Test
    fun rejectedAnswerUsesExactRefusalSentence() = runTest {
        val engine = FakeEngine { question -> answer(question, accepted = false) }
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("What is the capital of France?", "strict")
        advanceUntilIdle()

        val rejected = machine.state.value as AskState.Rejected
        assertEquals(GATE_REFUSAL_SENTENCE, rejected.refusal)
        assertEquals(
            "هذه المعلومة غير مذكورة في الكتب الطبية المدمجة في التطبيق.",
            rejected.refusal
        )
        assertEquals(listOf("What is the capital of France?" to "strict"), engine.calls)
    }

    @Test
    fun doubleTapOnTheSameRunningQuestionIsIgnored() = runTest {
        val engine = FakeEngine()
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("How is preeclampsia managed?", "balanced")
        advanceUntilIdle()
        machine.ask("How is preeclampsia managed?", "balanced")
        advanceUntilIdle()

        assertEquals(1, engine.calls.size)
        assertTrue(machine.state.value is AskState.Searching)

        engine.gates.removeFirst().complete(answer("How is preeclampsia managed?"))
        advanceUntilIdle()
        assertTrue(machine.state.value is AskState.Results)
    }

    @Test
    fun newQuestionCancelsRunningOneAndOnlyNewResultWins() = runTest {
        val engine = FakeEngine()
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("first question", "balanced")
        advanceUntilIdle()
        machine.ask("second question", "balanced")
        advanceUntilIdle()

        assertEquals(2, engine.calls.size)
        val second = engine.gates.last()
        second.complete(answer("second question"))
        advanceUntilIdle()

        val results = machine.state.value as AskState.Results
        assertEquals("second question", results.question)

        // Completing the cancelled request must not replace the newer result.
        engine.gates.first().complete(answer("first question"))
        advanceUntilIdle()
        assertEquals("second question", (machine.state.value as AskState.Results).question)
    }

    @Test
    fun cancelReturnsToReadyAndDropsLateResult() = runTest {
        val engine = FakeEngine()
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("question to cancel", "balanced")
        advanceUntilIdle()
        assertTrue(machine.state.value is AskState.Searching)

        machine.cancel()
        assertTrue(machine.state.value is AskState.Ready)

        engine.gates.removeFirst().complete(answer("question to cancel"))
        advanceUntilIdle()
        assertTrue(machine.state.value is AskState.Ready)
    }

    @Test
    fun engineFailureShowsError() = runTest {
        val engine = FakeEngine { throw IllegalStateException("onnx failed") }
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("question", "balanced")
        advanceUntilIdle()

        val error = machine.state.value as AskState.Error
        assertEquals("onnx failed", error.message)
    }

    @Test
    fun errorCanBeRetried() = runTest {
        val engine = FakeEngine { throw IllegalStateException("temporary failure") }
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("question", "balanced")
        advanceUntilIdle()
        assertTrue(machine.state.value is AskState.Error)

        engine.auto = { question -> answer(question) }
        machine.ask("question", "balanced")
        advanceUntilIdle()

        assertTrue(machine.state.value is AskState.Results)
        assertEquals(2, engine.calls.size)
    }

    @Test
    fun lateRuntimeErrorDoesNotReplaceSearchingState() = runTest {
        val engine = FakeEngine()
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("question", "balanced")
        advanceUntilIdle()
        machine.onError("late runtime failure")

        assertTrue(machine.state.value is AskState.Searching)

        engine.gates.removeFirst().complete(answer("question"))
        advanceUntilIdle()
        assertTrue(machine.state.value is AskState.Results)
    }

    @Test
    fun blankQuestionIsIgnored() = runTest {
        val engine = FakeEngine { question -> answer(question) }
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("   ", "balanced")
        advanceUntilIdle()

        assertTrue(machine.state.value is AskState.Ready)
        assertTrue(engine.calls.isEmpty())
    }

    @Test
    fun unknownPresetIsPassedToTheEngine() = runTest {
        val engine = FakeEngine { question -> answer(question) }
        val machine = AskStateMachine(engine, this)
        machine.onLoadingModel()
        machine.onReady()

        machine.ask("question", "custom")
        advanceUntilIdle()

        assertEquals("custom", engine.calls.single().second)
        assertFalse(machine.state.value is AskState.Installing)
        assertNull((machine.state.value as AskState.Results).decision.gateError)
    }
}
