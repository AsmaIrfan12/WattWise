package com.wattwise.userapp.ui.main

import android.webkit.JavascriptInterface
import com.wattwise.userapp.util.DeepLinks
import timber.log.Timber

/**
 * JavaScript <-> Android bridge, exposed to the dashboard as `window.WattWiseApp`.
 *
 *   window.WattWiseApp?.navigateTo("goals")
 *   window.WattWiseApp?.onLogout()            // the dashboard signed out / session expired
 *   window.WattWiseApp?.onTokenChanged(jwt)   // the dashboard signed in by itself
 *
 * The last two keep the app's own session in step with the page. Without them the app
 * kept an old token, put it back into the page on every load, and the background alert
 * check kept using it.
 *
 * Developer : Mr. Suhas Devmane, Cardiff University, UK
 */
class WattWiseJsBridge(
    private val onTabNavigation: (String) -> Unit,
    private val onLogoutRequest: () -> Unit,
    private val onTokenChange: (String) -> Unit,
    private val appVersion: String
) {

    /** Valid tab names: home, energy, devices, notifications, goals, ranking, settings */
    @JavascriptInterface
    fun navigateTo(tab: String?) {
        val safeTab = DeepLinks.sanitizeTab(tab)
        if (safeTab != null) onTabNavigation(safeTab) else Timber.w("JS bridge: unknown tab ignored")
    }

    @JavascriptInterface
    fun onLogout() {
        Timber.i("JS bridge: sign-out reported by the dashboard")
        onLogoutRequest()
    }

    @JavascriptInterface
    fun onTokenChanged(token: String?) {
        val t = token?.trim().orEmpty()
        if (DeepLinks.looksLikeJwt(t)) onTokenChange(t) else Timber.w("JS bridge: token ignored (not a JWT)")
    }

    @JavascriptInterface
    fun getPlatform(): String = "android"

    @JavascriptInterface
    fun getAppVersion(): String = appVersion

    @JavascriptInterface
    fun onDashboardReady(userId: String?) {
        Timber.i("JS bridge: dashboard ready")
    }
}
