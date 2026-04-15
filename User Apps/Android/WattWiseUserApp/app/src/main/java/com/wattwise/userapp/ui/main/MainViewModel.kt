package com.wattwise.userapp.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.wattwise.userapp.data.local.SecureTokenStore
import com.wattwise.userapp.data.repository.AuthRepository
import com.wattwise.userapp.data.repository.ServerRepository
import com.wattwise.userapp.domain.model.ConnectivityStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

/**
 * ViewModel for the main WebView screen.
 * Manages server URL state, connectivity, page loading, WebView URL persistence
 * across configuration changes (rotation), and session logout.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@HiltViewModel
class MainViewModel @Inject constructor(
    private val repository: ServerRepository,
    private val authRepository: AuthRepository,
    secureTokenStore: SecureTokenStore
) : ViewModel() {

    // ── Server URL (reactive) ─────────────────────────────────────────────
    val fullUrl: StateFlow<String> = repository.fullUrl
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), "")

    // Attach JWT as URL fragment so WebView dashboard can hydrate localStorage.
    // URL fragments are not sent to the server — they are client-side only.
    val webUrl: StateFlow<String> = combine(
        repository.fullUrl, secureTokenStore.token
    ) { baseUrl, token ->
        when {
            baseUrl.isBlank()      -> ""
            token.isNullOrBlank()  -> baseUrl
            else                   -> "$baseUrl#ww_token=$token"
        }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), "")

    // ── Network connectivity ──────────────────────────────────────────────
    val connectivity: StateFlow<ConnectivityStatus> = repository.connectivity
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), ConnectivityStatus.Available)

    val isConnected: StateFlow<Boolean> = repository.isConnected
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), true)

    // ── Page state ───────────────────────────────────────────────────────
    private val _isPageLoaded = MutableStateFlow(false)
    val isPageLoaded: StateFlow<Boolean> = _isPageLoaded.asStateFlow()

    private val _isError = MutableStateFlow(false)
    val isError: StateFlow<Boolean> = _isError.asStateFlow()

    private val _errorMessage = MutableStateFlow("")
    val errorMessage: StateFlow<String> = _errorMessage.asStateFlow()

    // ── WebView URL persistence across rotation ──────────────────────────
    // The ViewModel survives configuration changes; we save the last loaded URL
    // here so the UI can restore the WebView to the same page after rotation.
    private val _lastWebViewUrl = MutableStateFlow<String?>(null)
    val lastWebViewUrl: StateFlow<String?> = _lastWebViewUrl.asStateFlow()

    fun onWebViewUrlChanged(url: String) {
        if (url.isNotBlank() && !url.contains("#ww_token=")) {
            // Only persist navigation URLs, not the initial token-fragment URL
            _lastWebViewUrl.value = url
        }
    }

    // ── Logout ────────────────────────────────────────────────────────────
    private val _logoutEvent = MutableStateFlow(false)
    val logoutEvent: StateFlow<Boolean> = _logoutEvent.asStateFlow()

    fun logout() {
        viewModelScope.launch {
            try {
                authRepository.logout()
                Timber.i("🔒 MainViewModel: logout complete")
            } catch (e: Exception) {
                Timber.e(e, "Logout error (local cleared anyway)")
            } finally {
                _logoutEvent.value = true
            }
        }
    }

    fun logoutEventConsumed() {
        _logoutEvent.value = false
    }

    // ── Page callbacks ────────────────────────────────────────────────────
    fun onPageLoaded() {
        _isPageLoaded.value = true
        _isError.value = false
        Timber.d("✅ WebView page loaded")
    }

    fun onPageError(message: String) {
        _isPageLoaded.value = false
        _isError.value = true
        _errorMessage.value = message
        Timber.e("❌ WebView error: $message")
    }

    fun onRetry() {
        _isError.value = false
        _isPageLoaded.value = false
    }

    fun getNetworkType(): String = repository.getNetworkType()
    fun isCurrentlyConnected(): Boolean = repository.isCurrentlyConnected()
}
