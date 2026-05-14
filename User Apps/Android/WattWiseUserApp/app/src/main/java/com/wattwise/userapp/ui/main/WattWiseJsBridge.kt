package com.wattwise.userapp.ui.main

import android.webkit.JavascriptInterface
import timber.log.Timber

/**
 * JavaScript ↔ Android native bridge.
 *
 * Injected into the WebView as `window.WattWiseApp` so the web frontend can:
 *   - Navigate the WebView to a specific dashboard tab via deep-links
 *   - Signal a logout event back to the native layer
 *   - Query native app metadata (version, platform)
 *
 * Usage from web JS:
 *   window.WattWiseApp?.navigateTo("goals")
 *   window.WattWiseApp?.onLogout()
 *
 * Developer : Mr. Suhas Devmane, Cardiff University, UK
 * Version   : 4.0.0
 */
class WattWiseJsBridge(
    private val onTabNavigation: (String) -> Unit,
    private val onLogoutRequest: () -> Unit,
    private val appVersion: String
) {

    /**
     * Called by the web frontend to deep-link into a named tab.
     * Valid tab names: home, energy, devices, notifications, goals, ranking, settings
     */
    @JavascriptInterface
    fun navigateTo(tab: String) {
        val safeTabs = setOf("home", "energy", "devices", "notifications", "goals", "ranking", "settings")
        val safeTab = tab.lowercase().trim()
        if (safeTab in safeTabs) {
            Timber.d("🔗 JS bridge navigateTo: $safeTab")
            onTabNavigation(safeTab)
        } else {
            Timber.w("JS bridge: unknown tab '$tab' — ignored")
        }
    }

    /**
     * Called by the web frontend when the user taps Sign Out inside the WebView.
     * Routes the logout back through the native ViewModel so the local JWT is cleared.
     */
    @JavascriptInterface
    fun onLogout() {
        Timber.i("🔒 JS bridge: logout requested from WebView")
        onLogoutRequest()
    }

    /** Identifies the native app to the web frontend. */
    @JavascriptInterface
    fun getPlatform(): String = "android"

    /** Exposes the native app version string to the web frontend. */
    @JavascriptInterface
    fun getAppVersion(): String = appVersion

    /**
     * Called by the web frontend to signal that the user is authenticated
     * and the dashboard is fully hydrated — used for analytics/logging.
     */
    @JavascriptInterface
    fun onDashboardReady(userId: String) {
        Timber.i("✅ JS bridge: dashboard ready for userId=$userId")
    }
}
