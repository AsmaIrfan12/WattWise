package com.wattwise.userapp.data.local

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.notifDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "wattwise_notification_prefs"
)

/**
 * DataStore for notification polling state and app preferences.
 *
 * Stores:
 *  - [lastSeenNotificationId] — the ID of the most recently delivered local notification,
 *    used by [NotificationPollWorker] to avoid re-notifying for the same alerts.
 *  - [biometricEnabled] — user preference for biometric re-auth on resume.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@Singleton
class NotificationPrefsStore @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private object Keys {
        val LAST_NOTIF_ID = stringPreferencesKey("last_seen_notification_id")
        val BIOMETRIC_ENABLED = booleanPreferencesKey("biometric_unlock_enabled")
    }

    // ── Notification polling ──────────────────────────────────────────────

    /** The ID (as string) of the last notification shown to the user. */
    val lastSeenNotificationId: Flow<String> = context.notifDataStore.data.map { prefs ->
        prefs[Keys.LAST_NOTIF_ID] ?: ""
    }

    suspend fun setLastSeenNotificationId(id: String) {
        context.notifDataStore.edit { it[Keys.LAST_NOTIF_ID] = id }
    }

    // ── Biometric unlock ──────────────────────────────────────────────────

    /** Whether biometric re-authentication is enabled when the app resumes from background. */
    val biometricEnabled: Flow<Boolean> = context.notifDataStore.data.map { prefs ->
        prefs[Keys.BIOMETRIC_ENABLED] ?: false
    }

    suspend fun setBiometricEnabled(enabled: Boolean) {
        context.notifDataStore.edit { it[Keys.BIOMETRIC_ENABLED] = enabled }
    }
}
