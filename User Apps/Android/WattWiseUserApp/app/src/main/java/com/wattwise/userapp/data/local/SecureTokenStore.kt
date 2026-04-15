package com.wattwise.userapp.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Secure token storage using AndroidX EncryptedSharedPreferences (AES256-GCM).
 *
 * Replaces plain DataStore for JWT storage to prevent token extraction by
 * backup-snooping or root file-system access. Tokens are encrypted at rest
 * using the Android Keystore system key.
 *
 * Falls back to plain SharedPreferences only on devices where the Keystore
 * is unavailable (very old devices / emulators without hardware-backed keys),
 * logging a security warning.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@Singleton
class SecureTokenStore @Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        private const val FILE_NAME = "wattwise_secure_token"
        private const val KEY_JWT   = "jwt_access_token"
        private const val KEY_EMAIL = "user_email"
        private const val KEY_NAME  = "user_name"
    }

    // Backing state flow so callers can observe token changes reactively
    private val _tokenFlow = MutableStateFlow<String?>(null)

    /** Emits the current JWT token (null = not authenticated). Refreshed on every write. */
    val token: Flow<String?> = _tokenFlow.asStateFlow()

    /** Emits true when a non-empty token is present. */
    val isAuthenticated: Flow<Boolean> = _tokenFlow.asStateFlow().map { it?.isNotBlank() == true }

    private val prefs: SharedPreferences by lazy { buildPrefs() }

    private fun buildPrefs(): SharedPreferences {
        return try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()

            EncryptedSharedPreferences.create(
                context,
                FILE_NAME,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
        } catch (e: Exception) {
            Timber.e(e, "⚠️ EncryptedSharedPreferences unavailable — falling back to plain prefs")
            context.getSharedPreferences(FILE_NAME + "_plain", Context.MODE_PRIVATE)
        }
    }

    /** Load persisted token into the flow (call once at app start from DI/ViewModel). */
    suspend fun init() = withContext(Dispatchers.IO) {
        _tokenFlow.value = prefs.getString(KEY_JWT, null)
    }

    // ── Read ───────────────────────────────────────────────────────────────

    fun getTokenSync(): String? = prefs.getString(KEY_JWT, null)

    fun getEmailSync(): String? = prefs.getString(KEY_EMAIL, null)

    fun getNameSync():  String? = prefs.getString(KEY_NAME,  null)

    /** Returns "Bearer <token>" or null. */
    fun getBearerHeader(): String? {
        val t = getTokenSync()
        return if (t?.isNotBlank() == true) "Bearer $t" else null
    }

    // ── Write ──────────────────────────────────────────────────────────────

    suspend fun saveToken(token: String) = withContext(Dispatchers.IO) {
        prefs.edit().putString(KEY_JWT, token).apply()
        _tokenFlow.value = token
        Timber.d("🔐 JWT token saved to EncryptedSharedPreferences")
    }

    suspend fun saveUserInfo(email: String, name: String) = withContext(Dispatchers.IO) {
        prefs.edit()
            .putString(KEY_EMAIL, email)
            .putString(KEY_NAME,  name)
            .apply()
    }

    suspend fun clearAll() = withContext(Dispatchers.IO) {
        prefs.edit().clear().apply()
        _tokenFlow.value = null
        Timber.d("🔐 Secure token store cleared (logout)")
    }
}
