package com.wattwise.userapp.di

import com.wattwise.userapp.data.local.ServerPreferencesDataStore
import com.wattwise.userapp.util.ServerUrls
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The server address every API request is sent to (scheme + host + port).
 *
 * Read by the OkHttp URL-rewriting interceptor on a background thread. If a request is
 * made before the saved address has been loaded (the background alert check can start
 * the process on its own), the first read loads it from storage instead of silently
 * using the built-in default server.
 */
@Singleton
class ServerConfig @Inject constructor(
    private val prefs: ServerPreferencesDataStore
) {
    @Volatile
    private var cached: String? = null

    var baseUrl: String
        get() = cached ?: load()
        set(value) { cached = value }

    private fun load(): String {
        val loaded = runBlocking { ServerUrls.build(prefs.serverUrl.first(), prefs.port.first()) }
        cached = loaded
        return loaded
    }
}
