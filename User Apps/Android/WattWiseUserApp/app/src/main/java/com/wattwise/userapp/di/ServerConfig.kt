package com.wattwise.userapp.di

import com.wattwise.userapp.util.Constants
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Mutable holder for the currently configured server base URL.
 *
 * Initialised to [Constants.DEFAULT_SERVER_URL] at app start.
 * Updated when the user saves a new server URL in Settings.
 * Read synchronously by the OkHttp URL-rewriting interceptor.
 *
 * Thread-safe via @Volatile.
 */
@Singleton
class ServerConfig @Inject constructor() {
    @Volatile
    var baseUrl: String = Constants.DEFAULT_SERVER_URL
}
