package com.wattwise.userapp.data.remote

import com.wattwise.userapp.data.remote.model.NotificationItem
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.HEAD
import retrofit2.http.Header
import retrofit2.http.Query
import retrofit2.http.Url

/**
 * WattWise Retrofit API service.
 *
 * Handles:
 *  - Connection testing and lightweight health checks
 *  - Notification polling for background worker (FCM fallback)
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
interface WattWiseApiService {

    /**
     * Test whether the WattWise backend is reachable.
     * HEAD request for minimal bandwidth.
     */
    @HEAD
    suspend fun testConnection(@Url url: String): Response<Void>

    /**
     * Check backend health (FastAPI /health endpoint).
     */
    @GET
    suspend fun health(@Url url: String): Response<Void>

    /**
     * Fetch recent notification history for the authenticated user.
     * Used by [NotificationPollWorker] to detect new alerts.
     *
     * GET /api/notifications/history?limit=20&unread_only=true
     */
    @GET("/api/notifications/history")
    suspend fun getNotifications(
        @Header("Authorization") bearerToken: String,
        @Query("limit") limit: Int = 20,
        @Query("unread_only") unreadOnly: Boolean = true
    ): Response<List<NotificationItem>>
}
