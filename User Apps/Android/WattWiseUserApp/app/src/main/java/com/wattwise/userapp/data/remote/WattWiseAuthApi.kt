package com.wattwise.userapp.data.remote

import retrofit2.Response
import retrofit2.http.*

/**
 * Retrofit interface for WattWise FastAPI authentication endpoints.
 *
 * Separate from the main [WattWiseApiService] which is used for health checks.
 * These endpoints accept JSON body and return JWT access tokens.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
interface WattWiseAuthApi {

    /**
     * POST /api/auth/login
     * Body: { "email": "...", "password": "..." }
     * Returns: { "access_token": "...", "token_type": "bearer" }
     */
    @POST("/api/auth/login")
    suspend fun login(
        @Body credentials: Map<String, String>
    ): Response<Map<String, Any>>

    /**
     * POST /api/auth/signup
     * Body: { "name": "...", "email": "...", "password": "..." }
     * Returns: { "access_token": "...", "token_type": "bearer", "user_id": ... }
     */
    @POST("/api/auth/signup")
    suspend fun signup(
        @Body details: Map<String, String>
    ): Response<Map<String, Any>>

    /**
     * POST /api/auth/logout  (optional server-side invalidation)
     */
    @POST("/api/auth/logout")
    suspend fun logout(
        @Header("Authorization") bearerToken: String
    ): Response<Void>

    /**
     * POST /api/auth/forgot-password
     * Body: { "email": "..." }
     * Triggers a password reset email from the server.
     */
    @POST("/api/auth/forgot-password")
    suspend fun requestPasswordReset(
        @Body body: Map<String, String>
    ): Response<Map<String, Any>>
}
