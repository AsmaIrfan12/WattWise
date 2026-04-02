package com.wattwise.userapp.data.local

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.wattwise.userapp.util.Constants
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

// Extension property for DataStore — follows MAD best practice
private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(
    name = Constants.PREFERENCES_NAME
)

/**
 * Type-safe DataStore wrapper for server preferences.
 * Replaces SharedPreferences with reactive Flows.
 */
@Singleton
class ServerPreferencesDataStore @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private object Keys {
        val SERVER_URL = stringPreferencesKey("server_url")
        val PORT = intPreferencesKey("server_port")
        val TIMEOUT = intPreferencesKey("request_timeout_seconds")
    }

    // ── Read as Flows ──

    val serverUrl: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[Keys.SERVER_URL] ?: Constants.DEFAULT_SERVER_URL
    }

    val port: Flow<Int> = context.dataStore.data.map { prefs ->
        prefs[Keys.PORT] ?: Constants.DEFAULT_PORT
    }

    val timeout: Flow<Int> = context.dataStore.data.map { prefs ->
        prefs[Keys.TIMEOUT] ?: Constants.DEFAULT_TIMEOUT
    }

    // ── Write ──

    suspend fun setServerUrl(url: String) {
        context.dataStore.edit { it[Keys.SERVER_URL] = url }
    }

    suspend fun setPort(port: Int) {
        context.dataStore.edit { it[Keys.PORT] = port.coerceIn(1, 65535) }
    }

    suspend fun setTimeout(seconds: Int) {
        context.dataStore.edit { it[Keys.TIMEOUT] = seconds.coerceIn(3, 120) }
    }

    suspend fun resetToDefaults() {
        context.dataStore.edit { prefs ->
            prefs[Keys.SERVER_URL] = Constants.DEFAULT_SERVER_URL
            prefs[Keys.PORT] = Constants.DEFAULT_PORT
            prefs[Keys.TIMEOUT] = Constants.DEFAULT_TIMEOUT
        }
    }
}
