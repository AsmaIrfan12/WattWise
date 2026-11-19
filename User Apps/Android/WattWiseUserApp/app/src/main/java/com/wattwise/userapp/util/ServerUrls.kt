package com.wattwise.userapp.util

/**
 * Builds the one address the app talks to.
 *
 * The dashboard (WebView) and the API (Retrofit, background alert check) are served by
 * the same origin, so both must use exactly this value. Before, the WebView used
 * "url:port" while API calls used the URL alone, so a non-default port sent sign-in and
 * the alert check to the wrong place.
 */
object ServerUrls {

    /** Ports that mean "the default for the scheme": no suffix is added for them. */
    private val DEFAULT_PORTS = setOf(80, 443)

    fun build(url: String?, port: Int?): String {
        val base = (url ?: "").trim().trimEnd('/')
        if (base.isEmpty()) return Constants.DEFAULT_SERVER_URL
        if (port == null || port in DEFAULT_PORTS || hasExplicitPort(base)) return base
        return "$base:$port"
    }

    /** True for a usable http(s) address. */
    fun isValid(url: String?): Boolean {
        val u = (url ?: "").trim()
        if (!(u.startsWith("http://") || u.startsWith("https://"))) return false
        val host = u.substringAfter("://").substringBefore('/').substringBefore(':')
        return host.isNotBlank() && !host.contains(' ')
    }

    private fun hasExplicitPort(base: String): Boolean {
        val authority = base.substringAfter("://").substringBefore('/')
        val afterHost = authority.substringAfterLast(']', authority)   // skip IPv6 literals
        return afterHost.contains(':') && afterHost.substringAfterLast(':').toIntOrNull() != null
    }
}
