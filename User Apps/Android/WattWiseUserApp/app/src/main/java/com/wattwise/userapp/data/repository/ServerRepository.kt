package com.wattwise.userapp.data.repository

import com.wattwise.userapp.data.local.ServerPreferencesDataStore
import com.wattwise.userapp.data.remote.NetworkConnectivityObserver
import com.wattwise.userapp.data.remote.WattWiseApiService
import com.wattwise.userapp.di.ServerConfig
import com.wattwise.userapp.domain.model.ConnectivityStatus
import com.wattwise.userapp.domain.model.Resource
import com.wattwise.userapp.util.Constants
import com.wattwise.userapp.util.ServerUrls
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Single source of truth for server configuration and connectivity.
 * Keeps [ServerConfig.baseUrl] (used by every API request) equal to the address the
 * dashboard is loaded from, including the port.
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
        ServerUrls.build(url, port)
    }

    val connectivity: Flow<ConnectivityStatus> = connectivityObserver.observe

    val isConnected: Flow<Boolean> = connectivity.map { it is ConnectivityStatus.Available }

    suspend fun saveServer(url: String, port: Int, timeoutSeconds: Int) {
        val cleanUrl = url.trim().trimEnd('/')
        dataStore.setServerUrl(cleanUrl)
        dataStore.setPort(port)
        dataStore.setTimeout(timeoutSeconds)
        serverConfig.baseUrl = ServerUrls.build(cleanUrl, port)
    }

    suspend fun resetToDefaults() {
        dataStore.resetToDefaults()
        serverConfig.baseUrl = ServerUrls.build(Constants.DEFAULT_SERVER_URL, Constants.DEFAULT_PORT)
    }

    /** Tests the address typed in Settings (not the saved one). */
    suspend fun testConnection(url: String, port: Int): Resource<Int> {
        if (!ServerUrls.isValid(url)) {
            return Resource.Error("Enter an address starting with http:// or https://")
        }
        return try {
            val target = ServerUrls.build(url, port)
            val response = apiService.testConnection(target)
            Timber.d("Connection test: HTTP ${response.code()}")
            Resource.Success(response.code())
        } catch (e: Exception) {
            Timber.e(e, "Connection test failed")
            Resource.Error(e.message ?: "Connection failed", e)
        }
    }

    fun isCurrentlyConnected(): Boolean = connectivityObserver.isCurrentlyConnected()
    fun getNetworkType(): String = connectivityObserver.getNetworkType()
}
