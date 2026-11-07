package com.medai.assistant.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map

data class AppSettings(
    val preset: String = BALANCED,
    val showTimings: Boolean = false
) {
    companion object {
        const val BALANCED = "balanced"
        const val STRICT = "strict"
        val VALID_PRESETS = setOf(BALANCED, STRICT)
    }
}

val Context.settingsDataStore: DataStore<Preferences> by preferencesDataStore(name = "medai_settings")

class SettingsRepository(
    private val dataStore: DataStore<Preferences>
) {
    val settings: Flow<AppSettings> = dataStore.data
        .catch { emit(androidx.datastore.preferences.core.emptyPreferences()) }
        .map { preferences ->
            AppSettings(
                preset = normalizePreset(preferences[PRESET_KEY]),
                showTimings = preferences[SHOW_TIMINGS_KEY] ?: false
            )
        }
        .distinctUntilChanged()

    suspend fun setPreset(preset: String) {
        dataStore.edit { preferences ->
            preferences[PRESET_KEY] = normalizePreset(preset)
        }
    }

    suspend fun setShowTimings(show: Boolean) {
        dataStore.edit { preferences ->
            preferences[SHOW_TIMINGS_KEY] = show
        }
    }

    companion object {
        internal val PRESET_KEY = stringPreferencesKey("gate_preset")
        internal val SHOW_TIMINGS_KEY = booleanPreferencesKey("show_timings")

        /** Unknown or corrupted values fall back to the required default. */
        fun normalizePreset(value: String?): String {
            return if (value == AppSettings.STRICT) AppSettings.STRICT else AppSettings.BALANCED
        }
    }
}
