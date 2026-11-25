package com.wattwise.userapp.util

import java.net.URI

/**
 * Everything that turns outside input (notification extras, wattwise:// URIs, the
 * JS bridge) into something the WebView acts on goes through here.
 *
 * Nothing from an Intent or URI is ever placed into JavaScript directly: tabs are
 * matched against a fixed list and alert ids are parsed as numbers. Before this, the
 * exported wattwise://tab/<anything> link was interpolated straight into
 * evaluateJavascript(), letting any web page or app run script inside the dashboard.
 */
object DeepLinks {

    /** Sections of the web dashboard (the names goSection() accepts). */
    val TABS: Set<String> = setOf("home", "energy", "devices", "notifications", "goals", "ranking", "settings")

    private val ALIASES = mapOf("rankings" to "ranking", "alerts" to "notifications", "goal" to "goals")

    /** A known tab name, or null when the input is anything else. */
    fun sanitizeTab(raw: String?): String? {
        val tab = raw?.trim()?.lowercase() ?: return null
        val resolved = ALIASES[tab] ?: tab
        return if (resolved in TABS) resolved else null
    }

    /** A positive alert id, or null. */
    fun parseNotificationId(raw: String?): Long? = raw?.trim()?.toLongOrNull()?.takeIf { it > 0 }

    /**
     * JavaScript that navigates the dashboard. Built only from a whitelisted tab and
     * a number, so it cannot carry attacker-controlled text.
     */
    fun navigationJs(tab: String?, notificationId: Long?): String? {
        if (notificationId != null) {
            return "window.openAlertFromNative ? window.openAlertFromNative($notificationId) : window.goSection?.('notifications');"
        }
        val safeTab = sanitizeTab(tab) ?: return null
        return "window.goSection?.('$safeTab');"
    }

    /**
     * Asks the dashboard to handle Back. The page closes whatever is open on top, then
     * returns to the previous section, then to Home, and answers true; it answers false
     * when there is nothing left to go back to (or it is an older page without the hook).
     * A constant: nothing from outside is ever placed in it.
     */
    const val BACK_JS =
        "(function(){try{return !!(window.wwHandleBack&&window.wwHandleBack());}catch(e){return false;}})()"

    /** True when the dashboard's answer to [BACK_JS] says it handled Back itself. */
    fun dashboardHandledBack(jsResult: String?): Boolean = jsResult?.trim() == "true"

    /** Three base64url segments: the shape of a session token, nothing else. */
    fun looksLikeJwt(token: String?): Boolean {
        if (token == null || token.length !in 20..4096) return false
        val parts = token.split('.')
        return parts.size == 3 && parts.all { p -> p.isNotEmpty() && p.all { it.isLetterOrDigit() || it == '-' || it == '_' } }
    }

    /** True when [url] is served by the configured WattWise server (same scheme, host and port). */
    fun isServerUrl(url: String?, serverUrl: String?): Boolean {
        val a = origin(url) ?: return false
        val b = origin(serverUrl) ?: return false
        return a == b
    }

    private fun origin(url: String?): Triple<String, String, Int>? {
        if (url.isNullOrBlank()) return null
        return try {
            val uri = URI(url.trim().substringBefore('#'))
            val scheme = uri.scheme?.lowercase() ?: return null
            val host = uri.host?.lowercase() ?: return null
            if (scheme != "http" && scheme != "https") return null
            val port = if (uri.port != -1) uri.port else if (scheme == "https") 443 else 80
            Triple(scheme, host, port)
        } catch (e: Exception) {
            null
        }
    }
}
