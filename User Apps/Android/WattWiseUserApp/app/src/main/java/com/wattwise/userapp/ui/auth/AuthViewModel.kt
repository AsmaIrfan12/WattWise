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
 * Shared ViewModel for Login, Signup, and ForgotPassword screens.
 * Delegates all backend calls to [AuthRepository].
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@HiltViewModel
class AuthViewModel @Inject constructor(
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _loginState         = MutableStateFlow<AuthUiState>(AuthUiState.Idle)
    val loginState: StateFlow<AuthUiState> = _loginState.asStateFlow()

    private val _signupState        = MutableStateFlow<AuthUiState>(AuthUiState.Idle)
    val signupState: StateFlow<AuthUiState> = _signupState.asStateFlow()

    private val _resetPasswordState = MutableStateFlow<AuthUiState>(AuthUiState.Idle)
    val resetPasswordState: StateFlow<AuthUiState> = _resetPasswordState.asStateFlow()

    // ── Login ───────────────────────────────────────────────────────────────
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

    // ── Signup ──────────────────────────────────────────────────────────────
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

    // ── Forgot Password ──────────────────────────────────────────────────────
    fun requestPasswordReset(email: String) {
        if (_resetPasswordState.value is AuthUiState.Loading) return
        viewModelScope.launch {
            _resetPasswordState.value = AuthUiState.Loading
            val result = authRepository.requestPasswordReset(email.trim())
            _resetPasswordState.value = if (result.isSuccess) {
                AuthUiState.Success(result.getOrDefault("Reset email sent."))
            } else {
                AuthUiState.Error(result.exceptionOrNull()?.message ?: "Password reset failed")
            }
        }
    }

    // ── State resets ─────────────────────────────────────────────────────────
    fun resetLoginState()         { _loginState.value         = AuthUiState.Idle }
    fun resetSignupState()        { _signupState.value        = AuthUiState.Idle }
    fun resetPasswordResetState() { _resetPasswordState.value = AuthUiState.Idle }

    // ── Manual client-side error (validation) ─────────────────────────────────
    fun setError(message: String) { _loginState.value = AuthUiState.Error(message) }
}

/** Sealed hierarchy for UI state across auth flows. */
sealed class AuthUiState {
    data object Idle    : AuthUiState()
    data object Loading : AuthUiState()
    data class  Success(val message: String = "") : AuthUiState()
    data class  Error(val message: String)        : AuthUiState()
}
