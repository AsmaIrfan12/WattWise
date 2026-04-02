package com.wattwise.userapp.data.repository

import android.util.Patterns
import com.wattwise.userapp.data.local.TokenDataStore
import com.wattwise.userapp.data.remote.WattWiseApiService
import com.wattwise.userapp.data.remote.WattWiseAuthApi
import com.wattwise.userapp.util.Constants
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for authentication — login and signup against the FastAPI backend.
 *
 * Stores the JWT token in [TokenDataStore] after a successful login so subsequent
 * API calls (decisions, goals, rankings) can attach the `Authorization: Bearer` header.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@Singleton
class AuthRepository @Inject constructor(
    private val authApi: WattWiseAuthApi,
    private val tokenDataStore: TokenDataStore
) {

    /**
     * Call `POST /api/auth/login`.
     * On success, saves the JWT token in DataStore and returns [Result.success] with token.
     */
    suspend fun login(email: String, password: String): Result<String> {
        return try {
            validateEmail(email)?.let { return Result.failure(Exception(it)) }

            val response = authApi.login(
                mapOf("email" to email, "password" to password)
            )

            if (response.isSuccessful) {
                val body = response.body()
                val token = body?.get("access_token") as? String
                    ?: return Result.failure(Exception("Invalid server response"))
                tokenDataStore.saveToken(token)
                Result.success(token)
            } else {
                val errorMsg = when (response.code()) {
                    401  -> "Invalid email or password."
                    422  -> "Please check your email and password format."
                    500  -> "Server error — please try again later."
                    else -> "Login failed (${response.code()})"
                }
                Result.failure(Exception(errorMsg))
            }
        } catch (e: Exception) {
            Result.failure(Exception("Cannot reach WattWise server.\nPlease check your connection."))
        }
    }

    /**
     * Call `POST /api/auth/signup`.
     * Registers a new community participant. On success, auto-logs in and saves token.
     */
    suspend fun signup(name: String, email: String, password: String): Result<String> {
        return try {
            validateEmail(email)?.let { return Result.failure(Exception(it)) }
            if (name.length < 2)        return Result.failure(Exception("Please enter your full name."))
            if (password.length < 8)    return Result.failure(Exception("Password must be at least 8 characters."))

            val response = authApi.signup(
                mapOf("name" to name, "email" to email, "password" to password)
            )

            if (response.isSuccessful) {
                val body = response.body()
                val token = body?.get("access_token") as? String
                if (token != null) {
                    tokenDataStore.saveToken(token)
                    Result.success(token)
                } else {
                    // Signup succeeded but no token returned — try login
                    login(email, password)
                }
            } else {
                val errorMsg = when (response.code()) {
                    409  -> "An account with this email already exists."
                    422  -> "Please check your details and try again."
                    500  -> "Server error — please try again later."
                    else -> "Sign up failed (${response.code()})"
                }
                Result.failure(Exception(errorMsg))
            }
        } catch (e: Exception) {
            Result.failure(Exception("Cannot reach WattWise server.\nPlease check your connection."))
        }
    }

    /** Returns an error string if email is invalid, null if valid. */
    private fun validateEmail(email: String): String? {
        if (email.isBlank()) return "Please enter your email address."
        if (!Patterns.EMAIL_ADDRESS.matcher(email).matches()) return "Please enter a valid email address."
        return null
    }

    /** Clear stored token on logout. */
    suspend fun logout() = tokenDataStore.clearToken()
}
