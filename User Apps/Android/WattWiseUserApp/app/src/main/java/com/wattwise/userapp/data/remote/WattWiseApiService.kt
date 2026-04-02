package com.wattwise.userapp.data.remote

import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.HEAD
import retrofit2.http.Url

/**
 * WattWise Retrofit API service.
 * The main app UI is served via WebView; this interface handles
 * connection testing and lightweight health checks only.
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
}

