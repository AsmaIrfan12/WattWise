package com.wattwise.userapp.data.repository

import android.util.Patterns
import com.wattwise.userapp.data.local.SecureTokenStore
import com.wattwise.userapp.data.remote.WattWiseAuthApi
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for authentication — login, signup, logout, and password reset.
 *
 * Stores the JWT token in [SecureTokenStore] (EncryptedSharedPreferences / AES256-GCM)
 * after a successful login. Provides a server-side logout call as well as local token wipe.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@Singleton
class AuthRepository @Inject constructor(
    private val authApi: WattWiseAuthApi,
    private val secureTokenStore: SecureTokenStore
) {

    /** Reactive token flow — UI observes this to detect login/logout state. */
    val tokenFlow = secureTokenStore.token
    val isAuthenticated = secureTokenStore.isAuthenticated

    // ── Login ──────────────────────────────────────────────────────────────

    /**
     * POST /api/auth/login
     * On success: saves JWT to EncryptedSharedPreferences; returns Result.success(token).
     */
    suspend fun login(email: String, password: String): Result<String> {
        return try {
            validateEmail(email)?.let { return Result.failure(Exception(it)) }

            val response = authApi.login(mapOf("email" to email, "password" to password))

            if (response.isSuccessful) {
                val body  = response.body()
                val token = body?.get("access_token") as? String
                    ?: return Result.failure(Exception("Invalid server response — no token returned."))
                val name  = body["name"]  as? String ?: ""
                val mail  = body["email"] as? String ?: email

                secureTokenStore.saveToken(token)
                secureTokenStore.saveUserInfo(mail, name)
                Timber.i("✅ Login successful for $email")
                Result.success(token)
            } else {
                val errorMsg = when (response.code()) {
                    401  -> "Invalid email or password."
                    422  -> "Please check your email and password format."
                    403  -> "Your account has been disabled. Contact the administrator."
                    500  -> "Server error — please try again later."
                    else -> "Login failed (HTTP ${response.code()})"
                }
                Timber.w("Login failed: $errorMsg")
                Result.failure(Exception(errorMsg))
            }
        } catch (e: Exception) {
            Timber.e(e, "Login network error")
            Result.failure(Exception("Cannot reach WattWise server.\nPlease check your connection and server settings."))
        }
    }

    // ── Signup ─────────────────────────────────────────────────────────────

    /**
     * POST /api/auth/signup
     * Registers a new community participant. On success saves token and auto-logs in.
     */
    suspend fun signup(name: String, email: String, password: String): Result<String> {
        return try {
            validateEmail(email)?.let { return Result.failure(Exception(it)) }
            if (name.length < 2)     return Result.failure(Exception("Please enter your full name."))
            if (password.length < 8) return Result.failure(Exception("Password must be at least 8 characters."))

            val response = authApi.signup(mapOf("name" to name, "email" to email, "password" to password))

            if (response.isSuccessful) {
                val body  = response.body()
                val token = body?.get("access_token") as? String
                if (token != null) {
                    secureTokenStore.saveToken(token)
                    secureTokenStore.saveUserInfo(email, name)
                    Timber.i("✅ Signup successful for $email")
                    Result.success(token)
                } else {
                    // Signup succeeded but token not returned — auto-login
                    login(email, password)
                }
            } else {
                val errorMsg = when (response.code()) {
                    409  -> "An account with this email already exists."
                    422  -> "Please check your details and try again."
                    500  -> "Server error — please try again later."
                    else -> "Sign up failed (HTTP ${response.code()})"
                }
                Result.failure(Exception(errorMsg))
            }
        } catch (e: Exception) {
            Timber.e(e, "Signup network error")
            Result.failure(Exception("Cannot reach WattWise server.\nPlease check your connection."))
        }
    }

    // ── Logout ─────────────────────────────────────────────────────────────

    /**
     * Clears local token from EncryptedSharedPreferences AND notifies the server
     * (best-effort — local logout always succeeds even if server call fails).
     */
    suspend fun logout() {
        val bearer = secureTokenStore.getBearerHeader()
        if (bearer != null) {
            try {
                authApi.logout(bearer)
                Timber.i("🔒 Server-side logout acknowledged")
            } catch (e: Exception) {
                // Non-fatal — local token is cleared regardless
                Timber.w(e, "Server logout call failed (local logout still proceeding)")
            }
        }
        secureTokenStore.clearAll()
        Timber.i("🔒 Local session cleared")
    }

    // ── Forgot Password ────────────────────────────────────────────────────

    /**
     * POST /api/auth/forgot-password
     * Triggers a server-side password reset email. Returns success/failure.
     */
    suspend fun requestPasswordReset(email: String): Result<String> {
        return try {
            validateEmail(email)?.let { return Result.failure(Exception(it)) }

            val response = authApi.requestPasswordReset(mapOf("email" to email))
            if (response.isSuccessful) {
                Timber.i("📧 Password reset email requested for $email")
                Result.success("Password reset email sent to $email. Check your inbox.")
            } else {
                when (response.code()) {
                    404  -> Result.failure(Exception("No account found with that email address."))
                    429  -> Result.failure(Exception("Too many requests. Please wait a few minutes."))
                    else -> Result.failure(Exception("Could not send reset email (HTTP ${response.code()})"))
                }
            }
        } catch (e: Exception) {
            Timber.e(e, "Password reset request failed")
            Result.failure(Exception("Cannot reach WattWise server. Please check your connection."))
        }
    }

    // ── Helpers ────────────────────────────────────────────────────────────

    private fun validateEmail(email: String): String? {
        if (email.isBlank()) return "Please enter your email address."
        if (!Patterns.EMAIL_ADDRESS.matcher(email).matches()) return "Please enter a valid email address."
        return null
    }
}
