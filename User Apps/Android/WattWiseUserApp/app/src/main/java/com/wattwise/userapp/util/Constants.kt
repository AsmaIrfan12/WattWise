package com.wattwise.userapp.util

/**
 * WattWise — Application-wide constants.
 *
 * Developer : Mr. Suhas Devmane
 * Institution: Cardiff University, Wales, UK
 * School     : School of Computer Science & Informatics (COMSC)
 * Research   : PhD — Community-Level Energy Decision-Making & Behaviour Change
 * Version    : 4.0.0 (Community Release)
 */
object Constants {

    // ── Production Server ────────────────────────────────────────
    // Self-hosted Docker backend — update this to your server address.
    // Tailscale RPI tunnel: homeassistant.tail5340f7.ts.net
    // Local network fallback: http://192.168.x.x:8000
    const val DEFAULT_SERVER_URL = "https://www.talk2futurebuildings.systems"
    const val DEFAULT_PORT       = 443               // HTTPS
    const val DEFAULT_API_PORT   = 8000              // FastAPI backend (Docker)
    const val DEFAULT_TIMEOUT    = 20

    // ── Notification Channels ────────────────────────────────────
    const val NOTIFICATION_CHANNEL_ID_ENERGY    = "wattwise_energy_alerts"
    const val NOTIFICATION_CHANNEL_NAME_ENERGY  = "WattWise Energy Alerts"
    const val NOTIFICATION_CHANNEL_ID_INFO      = "wattwise_info"
    const val NOTIFICATION_CHANNEL_NAME_INFO    = "WattWise Updates"

    // ── Preferences DataStore ────────────────────────────────────
    const val PREFERENCES_NAME = "wattwise_user_app_prefs"

    // ── API Paths ────────────────────────────────────────────────
    const val API_LOGIN          = "/api/auth/login"
    const val API_SIGNUP         = "/api/auth/signup"
    const val API_NOTIFICATIONS  = "/api/notifications"
    const val API_GOALS          = "/api/goals"
    const val API_DECISIONS      = "/api/decisions"
    const val API_RANKINGS       = "/api/rankings/me"
    const val API_LEADERBOARD    = "/api/rankings/leaderboard"
    const val API_HEALTH         = "/health"

    // ── New Endpoints (migrated from old backend) ─────────────────
    const val API_SMART_NOTIFICATIONS = "/api/smart-notifications"
    const val API_DEVICE_CHECK        = "/api/smart-notifications/check"
    const val API_TRIGGER_NOTIFS      = "/api/smart-notifications/trigger"
    const val API_ENVIRONMENT_ROOMS   = "/api/environment/rooms"
    const val API_ENVIRONMENT_SUMMARY = "/api/environment/summary"
    const val API_INFLUX_ENTITIES     = "/api/influx/entities"
    const val API_INFLUX_HEALTH       = "/api/influx/health"
    const val API_ANALYSIS_REPORT     = "/api/analysis/report"
    const val API_BENCHMARK           = "/api/rankings/community-benchmark"

    // ── Developer & Research Details ─────────────────────────────
    const val DEVELOPER_NAME         = "Mr. Suhas Devmane"
    const val DEVELOPER_INSTITUTION  = "Cardiff University"
    const val DEVELOPER_SCHOOL       = "School of Computer Science & Informatics (COMSC)"
    const val DEVELOPER_LOCATION     = "Cardiff, Wales, United Kingdom"
    const val RESEARCH_DESCRIPTION   = "Community Energy Decision-Making & Behaviour Change"

    // ── App Metadata ─────────────────────────────────────────────
    const val APP_VERSION        = "4.0.0"
    const val APP_VERSION_NAME   = "Community Release"
    const val APP_TAGLINE        = "Track. Save. Compete."
    const val APP_YEAR           = "2024–2026"

    // Backward compat (keep for any references in existing code)
    const val DEVELOPER_CREDIT   = "$DEVELOPER_NAME, $DEVELOPER_INSTITUTION, UK"
}
