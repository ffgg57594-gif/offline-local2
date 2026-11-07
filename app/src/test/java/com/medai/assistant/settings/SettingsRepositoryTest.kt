package com.medai.assistant.settings

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class SettingsRepositoryTest {

    @get:Rule
    val temporaryFolder = TemporaryFolder()

    private fun newRepository(): Pair<SettingsRepository, CoroutineScope> {
        val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        val store = PreferenceDataStoreFactory.create(
            scope = scope,
            produceFile = {
                File(temporaryFolder.root, "settings-${System.nanoTime()}.preferences_pb")
            }
        )
        return SettingsRepository(store) to scope
    }

    @Test
    fun defaultsAreBalancedAndTimingsHidden() = runBlocking {
        val (repository, scope) = newRepository()
        try {
            val settings = repository.settings.first()
            assertEquals(AppSettings.BALANCED, settings.preset)
            assertFalse(settings.showTimings)
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun strictPresetIsPersisted() = runBlocking {
        val (repository, scope) = newRepository()
        try {
            repository.setPreset(AppSettings.STRICT)
            assertEquals(AppSettings.STRICT, repository.settings.first().preset)
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun unknownPresetFallsBackToBalanced() = runBlocking {
        val (repository, scope) = newRepository()
        try {
            repository.setPreset("unknown")
            assertEquals(AppSettings.BALANCED, repository.settings.first().preset)
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun showTimingsIsPersisted() = runBlocking {
        val (repository, scope) = newRepository()
        try {
            repository.setShowTimings(true)
            assertTrue(repository.settings.first().showTimings)
            repository.setShowTimings(false)
            assertFalse(repository.settings.first().showTimings)
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun presetNormalizationRules() {
        assertEquals(AppSettings.BALANCED, SettingsRepository.normalizePreset(null))
        assertEquals(AppSettings.BALANCED, SettingsRepository.normalizePreset(""))
        assertEquals(AppSettings.BALANCED, SettingsRepository.normalizePreset("garbage"))
        assertEquals(AppSettings.BALANCED, SettingsRepository.normalizePreset("BALANCED"))
        assertEquals(AppSettings.STRICT, SettingsRepository.normalizePreset("strict"))
    }
}
