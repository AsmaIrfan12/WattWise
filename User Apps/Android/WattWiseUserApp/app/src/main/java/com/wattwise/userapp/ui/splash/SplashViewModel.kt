package com.wattwise.userapp.ui.splash

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.wattwise.userapp.data.repository.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.async
import javax.inject.Inject

/**
 * Decides where the app opens: the dashboard when there is a working session, the
 * sign-in screen otherwise. The check runs while the splash animation plays.
 */
@HiltViewModel
class SplashViewModel @Inject constructor(
    authRepository: AuthRepository
) : ViewModel() {

    private val check = viewModelScope.async { authRepository.hasUsableSession() }

    suspend fun isSignedIn(): Boolean = check.await()
}
