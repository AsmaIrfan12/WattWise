package com.wattwise.userapp.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.wattwise.userapp.data.local.TokenDataStore
import com.wattwise.userapp.data.repository.ServerRepository
import com.wattwise.userapp.domain.model.ConnectivityStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import timber.log.Timber
import javax.inject.Inject

/**
 * ViewModel for the main WebView screen.
 * Manages server URL state, connectivity, and loading/error states.
 */
@HiltViewModel
class MainViewModel @Inject constructor(
    private val repository: ServerRepository,
    tokenDataStore: TokenDataStore
) : ViewModel() {

    // ── Server URL (reactive) ──
    val fullUrl: StateFlow<String> = repository.fullUrl
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), "")

    // Attach JWT as URL fragment so WebView dashboard can hydrate localStorage.
    // URL fragments are not sent to the server.
    val webUrl: StateFlow<String> = combine(repository.fullUrl, tokenDataStore.token) { baseUrl, token ->
        if (baseUrl.isBlank()) {
            ""
        } else if (token.isNullOrBlank()) {
            baseUrl
        } else {
            "$baseUrl#ww_token=$token"
        }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), "")

    // ── Network connectivity ──
    val connectivity: StateFlow<ConnectivityStatus> = repository.connectivity
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), ConnectivityStatus.Available)

    val isConnected: StateFlow<Boolean> = repository.isConnected
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), true)

    // ── UI state ──
    private val _isPageLoaded = MutableStateFlow(false)
    val isPageLoaded: StateFlow<Boolean> = _isPageLoaded.asStateFlow()

    private val _isError = MutableStateFlow(false)
    val isError: StateFlow<Boolean> = _isError.asStateFlow()

    private val _errorMessage = MutableStateFlow("")
    val errorMessage: StateFlow<String> = _errorMessage.asStateFlow()

    fun onPageLoaded() {
        _isPageLoaded.value = true
        _isError.value = false
        Timber.d("WebView page loaded")
    }

    fun onPageError(message: String) {
        _isPageLoaded.value = false
        _isError.value = true
        _errorMessage.value = message
        Timber.e("WebView error: $message")
    }

    fun onRetry() {
        _isError.value = false
        _isPageLoaded.value = false
    }

    fun getNetworkType(): String = repository.getNetworkType()
    fun isCurrentlyConnected(): Boolean = repository.isCurrentlyConnected()
}
