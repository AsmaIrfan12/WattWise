package com.wattwise.userapp

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.navigation.compose.rememberNavController
import com.wattwise.userapp.di.DeepLinkBus
import com.wattwise.userapp.ui.navigation.WattWiseNavGraph
import com.wattwise.userapp.ui.theme.WattWiseTheme
import com.wattwise.userapp.util.DeepLinks
import dagger.hilt.android.AndroidEntryPoint
import timber.log.Timber
import javax.inject.Inject

/**
 * Single Activity hosting the whole app via Jetpack Navigation for Compose.
 *
 * Handles deep links (wattwise://tab/<name>) and notification taps, which are passed to
 * the dashboard through [DeepLinkBus]. Notification channels are created in
 * [WattWiseApplication]; the notification permission is requested on the dashboard
 * screen, after sign-in.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject lateinit var deepLinkBus: DeepLinkBus

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            WattWiseTheme {
                val navController = rememberNavController()
                WattWiseNavGraph(navController = navController)
            }
        }

        // Only a fresh launch carries a new link. When Android re-creates the Activity
        // it hands back the same Intent, which would re-open an old alert.
        if (savedInstanceState == null) handleDeepLinkIntent(intent)
    }

    /** The app is already open (launchMode singleTop) and a notification or link is tapped. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleDeepLinkIntent(intent)
    }

    private fun handleDeepLinkIntent(intent: Intent?) {
        if (intent == null) return

        val rawTab: String? = when {
            intent.data?.scheme == "wattwise" && intent.data?.host == "tab" -> intent.data?.lastPathSegment
            intent.hasExtra("tab") -> intent.getStringExtra("tab")
            intent.hasExtra("screen") -> intent.getStringExtra("screen")
            else -> null
        }
        // This Activity is exported and BROWSABLE: the tab can come from any app or web
        // page, so only a known tab name is accepted (see DeepLinks).
        val tab = DeepLinks.sanitizeTab(rawTab)
        // A tapped alert notification also says WHICH alert, so the dashboard can open it.
        val notificationId = DeepLinks.parseNotificationId(intent.getStringExtra("notification_id"))

        if (tab != null || notificationId != null) {
            Timber.d("Deep link: tab=$tab notification=$notificationId")
            deepLinkBus.publish(tab ?: "notifications", notificationId)
        } else if (rawTab != null) {
            Timber.w("Ignored unknown deep-link target")
        }
    }
}
