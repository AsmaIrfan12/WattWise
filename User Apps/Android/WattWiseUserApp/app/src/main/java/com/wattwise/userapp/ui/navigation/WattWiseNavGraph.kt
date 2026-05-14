package com.wattwise.userapp.ui.navigation

import androidx.compose.runtime.Composable
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

/**
 * WattWise navigation graph.
 *
 * Flow:
 *   Splash ──(has token)──► Main (WebView)
 *          ──(no token) ──► Login
 *
 * Auth flow:
 *   Login ──(success)──────► Main
 *         ──(new user)───► Signup ──(success)──► Main
 *         ──(forgot pw)──► ForgotPassword ──► Login
 *
 * Settings flow:
 *   Main ──(settings icon)──► Settings ──(about row)──► About
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

@Composable
fun WattWiseNavGraph(
    navController: NavHostController,
    startWithAuth: Boolean = false
) {
    NavHost(
        navController = navController,
        startDestination = Routes.SPLASH
    ) {

        // ── Splash ─────────────────────────────────────────────────
        composable(Routes.SPLASH) {
            SplashScreen(
                onSplashFinished = {
                    val destination = if (startWithAuth) Routes.LOGIN else Routes.MAIN
                    navController.navigate(destination) {
                        popUpTo(Routes.SPLASH) { inclusive = true }
                    }
                }
            )
        }

        // ── Login ───────────────────────────────────────────────────
        composable(Routes.LOGIN) {
            LoginScreen(
                onLoginSuccess = {
                    navController.navigate(Routes.MAIN) {
                        popUpTo(Routes.LOGIN) { inclusive = true }
                    }
                },
                onNavigateToSignup = {
                    navController.navigate(Routes.SIGNUP)
                },
                onNavigateToForgotPassword = {
                    navController.navigate(Routes.FORGOT_PASSWORD)
                }
            )
        }

        // ── Signup ──────────────────────────────────────────────────
        composable(Routes.SIGNUP) {
            SignupScreen(
                onSignupSuccess = {
                    navController.navigate(Routes.MAIN) {
                        popUpTo(Routes.LOGIN) { inclusive = true }
                    }
                },
                onNavigateToLogin = {
                    navController.popBackStack()
                }
            )
        }

        // ── Forgot Password ─────────────────────────────────────────
        composable(Routes.FORGOT_PASSWORD) {
            ForgotPasswordScreen(
                onNavigateBack = {
                    navController.popBackStack()
                }
            )
        }

        // ── Main WebView Dashboard ───────────────────────────────────
        composable(Routes.MAIN) {
            MainScreen(
                onNavigateToSettings = {
                    navController.navigate(Routes.SETTINGS)
                },
                onLogout = {
                    // Full logout: clear back stack back to login
                    navController.navigate(Routes.LOGIN) {
                        popUpTo(0) { inclusive = true }
                    }
                }
            )
        }

        // ── Settings ────────────────────────────────────────────────
        composable(Routes.SETTINGS) {
            SettingsScreen(
                onNavigateBack = { navController.popBackStack() },
                onNavigateToAbout = {
                    navController.navigate(Routes.ABOUT)
                },
                onLogout = {
                    navController.navigate(Routes.LOGIN) {
                        popUpTo(0) { inclusive = true }
                    }
                }
            )
        }

        // ── About ───────────────────────────────────────────────────
        composable(Routes.ABOUT) {
            AboutScreen(
                onNavigateBack = { navController.popBackStack() }
            )
        }
    }
}
