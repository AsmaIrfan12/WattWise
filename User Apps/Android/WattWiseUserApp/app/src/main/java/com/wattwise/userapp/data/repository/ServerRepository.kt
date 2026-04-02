package com.wattwise.userapp.data.repository

import com.wattwise.userapp.data.local.ServerPreferencesDataStore
import com.wattwise.userapp.data.remote.WattWiseApiService
import com.wattwise.userapp.data.remote.NetworkConnectivityObserver
import com.wattwise.userapp.di.ServerConfig
import com.wattwise.userapp.domain.model.ConnectivityStatus
import com.wattwise.userapp.domain.model.Resource
import com.wattwise.userapp.util.Constants
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Single source of truth for server configuration and connectivity.
 * Combines DataStore preferences with Retrofit connection testing.
 * Updates [ServerConfig.baseUrl] whenever the user saves a new address
 * so the OkHttp interceptor picks it up on the next request.
 */
@Singleton
class ServerRepository @Inject constructor(
    private val dataStore: ServerPreferencesDataStore,
    private val apiService: WattWiseApiService,
    private val connectivityObserver: NetworkConnectivityObserver,
    private val serverConfig: ServerConfig
) {
    val serverUrl: Flow<String> = dataStore.serverUrl
    val port: Flow<Int> = dataStore.port
    val timeout: Flow<Int> = dataStore.timeout

    val fullUrl: Flow<String> = combine(dataStore.serverUrl, dataStore.port) { url, port ->
        buildFullUrl(url, port)
    }

    val connectivity: Flow<ConnectivityStatus> = connectivityObserver.observe

    val isConnected: Flow<Boolean> = connectivity.map { it is ConnectivityStatus.Available }

    suspend fun updateServerUrl(url: String) {
        dataStore.setServerUrl(url)
        serverConfig.baseUrl = url
    }

    suspend fun updatePort(port: Int) = dataStore.setPort(port)
    suspend fun updateTimeout(seconds: Int) = dataStore.setTimeout(seconds)

    suspend fun resetToDefaults() {
        dataStore.resetToDefaults()
        serverConfig.baseUrl = Constants.DEFAULT_SERVER_URL
    }

    suspend fun testConnection(url: String, port: Int): Resource<Int> {
        return try {
            val fullUrl = buildFullUrl(url, port)
            Timber.d("Testing connection to: $fullUrl")
            val response = apiService.testConnection(fullUrl)
            val code = response.code()
            Timber.d("Connection test result: HTTP $code")
            Resource.Success(code)
        } catch (e: Exception) {
            Timber.e(e, "Connection test failed")
            Resource.Error(e.message ?: "Connection failed", e)
        }
    }

    fun isCurrentlyConnected(): Boolean = connectivityObserver.isCurrentlyConnected()
    fun getNetworkType(): String = connectivityObserver.getNetworkType()

    private fun buildFullUrl(url: String, port: Int): String {
        val base = url.trimEnd('/')
        return if (port == 443 || port == 80) base else "$base:$port"
    }
}
