package com.wattwise.userapp

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.compose.rememberNavController
import com.wattwise.userapp.ui.main.MainViewModel
import com.wattwise.userapp.ui.navigation.WattWiseNavGraph
import com.wattwise.userapp.ui.theme.WattWiseTheme
import com.wattwise.userapp.util.Constants
import dagger.hilt.android.AndroidEntryPoint
import timber.log.Timber

/**
 * Single Activity hosting the entire app via Jetpack Navigation for Compose.
 * All screens (Splash, Main/WebView, Settings, About) are composable destinations.
 *
 * Handles:
 *  - Edge-to-edge display
 *  - Notification channel creation
 *  - Deep-link Intents (wattwise://tab/<tabname> → WebView tab navigation)
 *  - Notification tap Intents → routes to correct dashboard tab
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Notification channels are also created in WattWiseApplication,
        // but we recreate here as a safety net for older OS upgrades.
        createNotificationChannels()

        enableEdgeToEdge()

        setContent {
            WattWiseTheme {
                val navController = rememberNavController()
                WattWiseNavGraph(navController = navController)
            }
        }

        // Handle deep-link Intent if the Activity was launched (not resumed) via one
        handleDeepLinkIntent(intent)
    }

    /**
     * Called when the Activity is already running and a new Intent arrives
     * (e.g. user taps a notification while app is in the foreground).
     */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleDeepLinkIntent(intent)
    }

    // ── Deep-link handling ────────────────────────────────────────────────

    /**
     * Extracts the tab name from a wattwise://tab/<name> URI or from
     * a notification Intent extra ("tab" key), then queues it in MainViewModel
     * so the WebView navigates to the correct section.
     *
     * Examples:
     *   wattwise://tab/notifications → goSection('notifications')
     *   wattwise://tab/goals        → goSection('goals')
     *   Intent extra "tab" = "devices" → goSection('devices')
     */
    private fun handleDeepLinkIntent(intent: Intent?) {
        if (intent == null) return

        val tab: String? = when {
            // URI deep-link: wattwise://tab/notifications
            intent.data?.scheme == "wattwise" && intent.data?.host == "tab" -> {
                intent.data?.lastPathSegment
            }
            // Notification extra: Bundle with key "tab"
            intent.hasExtra("tab") -> intent.getStringExtra("tab")
            // Notification extra: Bundle with key "screen"
            intent.hasExtra("screen") -> intent.getStringExtra("screen")?.lowercase()
            else -> null
        }

        if (!tab.isNullOrBlank()) {
            Timber.d("🔗 MainActivity deep-link: tab=$tab")
            // The MainViewModel is shared with MainScreen via Hilt — queue the tab
            try {
                val vm = ViewModelProvider(this)[MainViewModel::class.java]
                vm.handleDeepLink(tab)
            } catch (e: Exception) {
                Timber.w(e, "Could not route deep-link (MainViewModel not yet created)")
            }
        }
    }

    // ── Notification channels ─────────────────────────────────────────────
    private fun createNotificationChannels() {
        val manager = getSystemService(NotificationManager::class.java)

        // Channel 1: Energy Alerts (high importance — peak tariff, critical usage)
        NotificationChannel(
            Constants.NOTIFICATION_CHANNEL_ID_ENERGY,
            Constants.NOTIFICATION_CHANNEL_NAME_ENERGY,
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "Critical energy alerts from WattWise smart plugs"
            enableLights(true)
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 300, 200, 300)
            setSound(
                RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION),
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            manager.createNotificationChannel(this)
        }

        // Channel 2: General Info (lower importance — weekly summaries, tips)
        NotificationChannel(
            Constants.NOTIFICATION_CHANNEL_ID_INFO,
            Constants.NOTIFICATION_CHANNEL_NAME_INFO,
            NotificationManager.IMPORTANCE_DEFAULT
        ).apply {
            description = "Weekly reports and energy tips from WattWise"
            enableVibration(false)
            manager.createNotificationChannel(this)
        }
    }
}
