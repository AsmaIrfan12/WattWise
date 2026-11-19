package com.wattwise.userapp.ui.navigation

import android.webkit.CookieManager
import android.webkit.WebStorage
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import com.wattwise.userapp.ui.about.AboutScreen
import com.wattwise.userapp.ui.auth.ForgotPasswordScreen
import com.wattwise.userapp.ui.auth.LoginScreen
import com.wattwise.userapp.ui.auth.SignupScreen
import com.wattwise.userapp.ui.main.MainScreen
import com.wattwise.userapp.ui.settings.SettingsScreen
import com.wattwise.userapp.ui.splash.SplashScreen
import com.wattwise.userapp.ui.splash.SplashViewModel
import kotlinx.coroutines.launch

/**
 * WattWise navigation graph.
 *
 *   Splash --(working session)--> Main (dashboard)
 *          --(none / expired)---> Login
 *
 *   Login --> Main          Login --> Signup --> Main
 *   Login --> ForgotPassword          Login --> Settings (server address)
 *   Main  --> Settings --> About
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
object Routes {
    const val SPLASH           = "splash"
    const val LOGIN            = "login"
    const val SIGNUP           = "signup"
    const val FORGOT_PASSWORD  = "forgot_password"
    const val MAIN             = "main"
    const val SETTINGS         = "settings"
    const val ABOUT            = "about"
}

/** Removes what the dashboard page stored, so a signed-out session cannot linger in the WebView. */
private fun clearWebSession() {
    try {
        WebStorage.getInstance().deleteAllData()
        CookieManager.getInstance().removeAllCookies(null)
    } catch (e: Exception) {
        // WebView not available on this device right now: nothing to clear.
    }
}

@Composable
fun WattWiseNavGraph(navController: NavHostController) {
    val toLoginAfterSignOut: () -> Unit = {
        clearWebSession()
        navController.navigate(Routes.LOGIN) {
            popUpTo(0) { inclusive = true }
        }
    }

    NavHost(
        navController = navController,
        startDestination = Routes.SPLASH
    ) {

        composable(Routes.SPLASH) {
            val splashViewModel: SplashViewModel = hiltViewModel()
            val scope = rememberCoroutineScope()
            SplashScreen(
                onSplashFinished = {
                    scope.launch {
                        val destination = if (splashViewModel.isSignedIn()) Routes.MAIN else Routes.LOGIN
                        navController.navigate(destination) {
                            popUpTo(Routes.SPLASH) { inclusive = true }
                        }
                    }
                }
            )
        }

        composable(Routes.LOGIN) {
            LoginScreen(
                onLoginSuccess = {
                    navController.navigate(Routes.MAIN) {
                        popUpTo(Routes.LOGIN) { inclusive = true }
                    }
                },
                onNavigateToSignup = { navController.navigate(Routes.SIGNUP) },
                onNavigateToForgotPassword = { navController.navigate(Routes.FORGOT_PASSWORD) },
                onNavigateToSettings = { navController.navigate(Routes.SETTINGS) }
            )
        }

        composable(Routes.SIGNUP) {
            SignupScreen(
                onSignupSuccess = {
                    navController.navigate(Routes.MAIN) {
                        popUpTo(Routes.LOGIN) { inclusive = true }
                    }
                },
                onNavigateToLogin = { navController.popBackStack() }
            )
        }

        composable(Routes.FORGOT_PASSWORD) {
            ForgotPasswordScreen(onNavigateBack = { navController.popBackStack() })
        }

        composable(Routes.MAIN) {
            MainScreen(
                onNavigateToSettings = { navController.navigate(Routes.SETTINGS) },
                onLogout = toLoginAfterSignOut
            )
        }

        composable(Routes.SETTINGS) {
            SettingsScreen(
                onNavigateBack = { navController.popBackStack() },
                onNavigateToAbout = { navController.navigate(Routes.ABOUT) },
                onLogout = toLoginAfterSignOut
            )
        }

        composable(Routes.ABOUT) {
            AboutScreen(onNavigateBack = { navController.popBackStack() })
        }
    }
}
