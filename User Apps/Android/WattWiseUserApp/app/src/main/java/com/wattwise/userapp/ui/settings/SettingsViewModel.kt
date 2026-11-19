package com.wattwise.userapp.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.wattwise.userapp.data.repository.AuthRepository
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
 * ViewModel for the Settings screen: server address, connection test, sign out.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val repository: ServerRepository,
    private val authRepository: AuthRepository
) : ViewModel() {

    val serverUrl: StateFlow<String> = repository.serverUrl
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), "")

    val port: StateFlow<Int> = repository.port
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 80)

    val timeout: StateFlow<Int> = repository.timeout
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 20)

    private val _testResult = MutableStateFlow<Resource<Int>?>(null)
    val testResult: StateFlow<Resource<Int>?> = _testResult.asStateFlow()

    fun saveSettings(url: String, port: Int, timeout: Int, onSaved: () -> Unit = {}) {
        viewModelScope.launch {
            repository.saveServer(url, port, timeout)
            Timber.d("Server settings saved")
            onSaved()
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
        }
    }

    fun getNetworkType(): String = repository.getNetworkType()
    fun isConnected(): Boolean = repository.isCurrentlyConnected()

    /**
     * Signs out for real: the session token the dashboard and the background alert
     * check use is removed. (This used to clear a different, unused store, so the user
     * was signed straight back in on the next launch.)
     */
    fun logout(onComplete: () -> Unit) {
        viewModelScope.launch {
            try {
                authRepository.logout()
            } catch (e: Exception) {
                Timber.e(e, "Sign-out error")
            }
            onComplete()
        }
    }
}
