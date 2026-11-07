package com.medai.assistant.gate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * K4 test (c): hand-made unit cases with explicitly defined behaviour.
 *
 * Expected stem strings were produced by the real FTS5
 * `porter unicode61 remove_diacritics 2` tokenizer.
 */
class GateContentStemsTest {

    private val vocab: GateVocab by lazy { GateVocab.load(GateTestAssets.vocab) }

    private fun stems(question: String): List<String> {
        JdbcGateDatabase(GateTestAssets.database).use { database ->
            return ContentStems.contentStems(question, vocab, database)
        }
    }

    private fun signals(question: String): GateSignalResult {
        JdbcGateDatabase(GateTestAssets.database).use { database ->
            return GateSignals.compute(question, emptyList(), database, vocab)
        }
    }

    @Test
    fun testPossessiveApostropheIsStripped() {
        val straight = stems("What causes Asherman's syndrome?")
        val curly = stems("What causes Asherman\u2019s syndrome?")
        assertEquals(listOf("caus", "asherman", "syndrom"), straight)
        assertEquals(straight, curly)
        assertTrue(straight.none { it.contains("'") || it.contains("\u2019") })
    }

    @Test
    fun testHyphenCompoundExpansionIsSymmetric() {
        assertEquals(listOf("vesico", "vagin"), stems("vesicovaginal"))
        assertEquals(listOf("vesico", "vagin"), stems("vesico-vaginal"))
        assertEquals(listOf("tension", "free"), stems("tensionfree"))
        assertEquals(listOf("tension", "free"), stems("tension-free"))
    }

    @Test
    fun testDigitsAndSingleLettersAreDropped() {
        assertEquals(listOf("stage", "hypertens"), stems("stage 2 hypertension"))
        assertEquals(emptyList<String>(), stems("2 5 2018"))
    }

    @Test
    fun testUnknownTermsAreCountedInS4() {
        val result = signals("zzzqwerty unknownword")
        assertEquals(listOf("zzzqwerti", "unknownword"), result.stems)
        assertEquals(listOf("zzzqwerti", "unknownword"), result.unknownStems)
        assertEquals(2, result.s4Unknown)
        assertEquals(0.0, result.s3CovTop3, 0.0)
    }

    @Test
    fun testEmptyQuestionHasNoStemsAndZeroScores() {
        val result = signals("")
        assertEquals(emptyList<String>(), result.stems)
        assertEquals(emptyList<String>(), result.unknownStems)
        assertEquals(0, result.s4Unknown)
        assertEquals(0.0, result.s3CovTop3, 0.0)
    }

    @Test
    fun testStopwordOnlyQuestionHasNoStems() {
        val result = signals("the is a of and how what")
        assertEquals(emptyList<String>(), result.stems)
        assertEquals(0, result.s4Unknown)
        assertEquals(0.0, result.s3CovTop3, 0.0)
    }

    @Test
    fun testDecisionBoundariesUseEpsilon() {
        // Midpoint-style thresholds, not equal to any observed value.
        val preset = GatePreset(t1 = 0.8400005, t3 = 0.5357145, k = 0)
        assertTrue(GateDecision.accept(0.8400005, 0.5357145, 0, preset))
        // 1e-6 tolerance: values up to epsilon below the threshold are accepted.
        assertTrue(GateDecision.accept(0.8400005 - 5e-7, 0.5357145, 0, preset))
        assertFalse(GateDecision.accept(0.8400005 - 2e-6, 0.5357145, 0, preset))
        assertTrue(GateDecision.accept(0.8400005, 0.5357145 - 5e-7, 0, preset))
        assertFalse(GateDecision.accept(0.8400005, 0.5357145 - 2e-6, 0, preset))
        assertFalse(GateDecision.accept(0.8400005, 0.5357145, 1, preset))
    }
}
