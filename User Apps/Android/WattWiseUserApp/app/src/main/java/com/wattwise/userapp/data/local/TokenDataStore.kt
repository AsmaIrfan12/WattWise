package com.wattwise.userapp.data.local

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

// Dedicated DataStore for auth token — separate from ServerPreferencesDataStore.
// Uses a DIFFERENT name ('wattwise_token_prefs') to avoid the private extension
// property conflict with ServerPreferencesDataStore.kt's 'wattwise_user_app_prefs'.
private val Context.tokenDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "wattwise_token_prefs"
)

/**
 * DataStore wrapper for the JWT authentication token.
 * Uses its own dedicated DataStore instance so it does not conflict with the
 * private [Context.dataStore] extension in [ServerPreferencesDataStore].
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@Singleton
class TokenDataStore @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private object Keys {
        val JWT_TOKEN  = stringPreferencesKey("jwt_access_token")
        val USER_EMAIL = stringPreferencesKey("user_email")
        val USER_NAME  = stringPreferencesKey("user_name")
    }

    /** Emits the stored JWT token, or null if not authenticated. */
    val token: Flow<String?> = context.tokenDataStore.data.map { prefs ->
        prefs[Keys.JWT_TOKEN]
    }

    /** Emits true if a valid token is stored. */
    val isAuthenticated: Flow<Boolean> = token.map { it?.isNotBlank() == true }

    /** Emits the stored user email. */
    val userEmail: Flow<String?> = context.tokenDataStore.data.map { prefs ->
        prefs[Keys.USER_EMAIL]
    }

    /** Emits the stored user full name. */
    val userName: Flow<String?> = context.tokenDataStore.data.map { prefs ->
        prefs[Keys.USER_NAME]
    }

    // ── Write ──────────────────────────────────────────────────────────

    suspend fun saveToken(token: String) {
        context.tokenDataStore.edit { it[Keys.JWT_TOKEN] = token }
    }

    suspend fun saveUserInfo(email: String, name: String) {
        context.tokenDataStore.edit { prefs ->
            prefs[Keys.USER_EMAIL] = email
            prefs[Keys.USER_NAME]  = name
        }
    }

    suspend fun clearToken() {
        context.tokenDataStore.edit { prefs ->
            prefs.remove(Keys.JWT_TOKEN)
            prefs.remove(Keys.USER_EMAIL)
            prefs.remove(Keys.USER_NAME)
        }
    }

    /** Returns "Bearer <token>" or null if not authenticated. */
    suspend fun getBearerHeader(): String? {
        val t = context.tokenDataStore.data.map { it[Keys.JWT_TOKEN] }.first()
        return if (t?.isNotBlank() == true) "Bearer $t" else null
    }
}
