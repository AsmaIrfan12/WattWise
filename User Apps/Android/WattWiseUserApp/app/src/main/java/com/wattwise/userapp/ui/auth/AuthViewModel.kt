package com.wattwise.userapp.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.wattwise.userapp.data.repository.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Shared ViewModel for Login and Signup screens.
 * Calls the WattWise FastAPI backend via [AuthRepository].
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@HiltViewModel
class AuthViewModel @Inject constructor(
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _loginState  = MutableStateFlow<AuthUiState>(AuthUiState.Idle)
    val loginState: StateFlow<AuthUiState> = _loginState.asStateFlow()

    private val _signupState = MutableStateFlow<AuthUiState>(AuthUiState.Idle)
    val signupState: StateFlow<AuthUiState> = _signupState.asStateFlow()

    // ── Login ──────────────────────────────────────────────────────────
    fun login(email: String, password: String) {
        if (_loginState.value is AuthUiState.Loading) return
        viewModelScope.launch {
            _loginState.value = AuthUiState.Loading
            val result = authRepository.login(email.trim(), password)
            _loginState.value = if (result.isSuccess) {
                AuthUiState.Success(result.getOrDefault(""))
            } else {
                AuthUiState.Error(result.exceptionOrNull()?.message ?: "Login failed")
            }
        }
    }

    // ── Signup ─────────────────────────────────────────────────────────
    fun signup(name: String, email: String, password: String) {
        if (_signupState.value is AuthUiState.Loading) return
        viewModelScope.launch {
            _signupState.value = AuthUiState.Loading
            val result = authRepository.signup(name.trim(), email.trim(), password)
            _signupState.value = if (result.isSuccess) {
                AuthUiState.Success(result.getOrDefault(""))
            } else {
                AuthUiState.Error(result.exceptionOrNull()?.message ?: "Signup failed")
            }
        }
    }

    // ── Reset state ────────────────────────────────────────────────────
    fun resetLoginState()  { _loginState.value  = AuthUiState.Idle }
    fun resetSignupState() { _signupState.value = AuthUiState.Idle }

    // ── Manual error (e.g. client-side validation) ─────────────────────
    fun setError(message: String) { _loginState.value = AuthUiState.Error(message) }
}

/** Sealed hierarchy for UI state across login/signup flows. */
sealed class AuthUiState {
    data object Idle    : AuthUiState()
    data object Loading : AuthUiState()
    data class  Success(val token: String) : AuthUiState()
    data class  Error(val message: String) : AuthUiState()
}
