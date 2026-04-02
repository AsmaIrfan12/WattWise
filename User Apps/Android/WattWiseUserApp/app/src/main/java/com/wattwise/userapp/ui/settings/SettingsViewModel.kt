package com.wattwise.userapp.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.wattwise.userapp.data.local.TokenDataStore
import com.wattwise.userapp.data.repository.ServerRepository
import com.wattwise.userapp.domain.model.Resource
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

/**
 * ViewModel for the Settings screen.
 * Manages server config CRUD and connection testing.
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val repository: ServerRepository,
    private val tokenDataStore: TokenDataStore
) : ViewModel() {

    // ── Reactive preferences ──
    val serverUrl: StateFlow<String> = repository.serverUrl
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), "")

    val port: StateFlow<Int> = repository.port
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 443)

    val timeout: StateFlow<Int> = repository.timeout
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 20)

    // ── Connection test state ──
    private val _testResult = MutableStateFlow<Resource<Int>?>(null)
    val testResult: StateFlow<Resource<Int>?> = _testResult.asStateFlow()

    // ── Actions ──

    fun saveSettings(url: String, port: Int, timeout: Int) {
        viewModelScope.launch {
            repository.updateServerUrl(url)
            repository.updatePort(port)
            repository.updateTimeout(timeout)
            Timber.d("Settings saved: $url:$port (timeout: ${timeout}s)")
        }
    }

    fun testConnection(url: String, port: Int) {
        viewModelScope.launch {
            _testResult.value = Resource.Loading
            _testResult.value = repository.testConnection(url, port)
        }
    }

    fun resetToDefaults() {
        viewModelScope.launch {
            repository.resetToDefaults()
            _testResult.value = null
            Timber.d("Settings reset to defaults")
        }
    }

    fun getNetworkType(): String = repository.getNetworkType()
    fun isConnected(): Boolean = repository.isCurrentlyConnected()

    fun logout(onComplete: () -> Unit) {
        viewModelScope.launch {
            tokenDataStore.clearToken()
            Timber.d("User logged out — token cleared")
            onComplete()
        }
    }
}
