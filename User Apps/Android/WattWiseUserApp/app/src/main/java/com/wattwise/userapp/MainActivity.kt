package com.wattwise.userapp

import android.app.NotificationChannel
import android.app.NotificationManager
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.navigation.compose.rememberNavController
import com.wattwise.userapp.ui.navigation.WattWiseNavGraph
import com.wattwise.userapp.ui.theme.WattWiseTheme
import com.wattwise.userapp.util.Constants
import dagger.hilt.android.AndroidEntryPoint

/**
 * Single Activity hosting the entire app via Jetpack Navigation for Compose.
 * All screens (Splash, Main/WebView, Settings) are composable destinations.
 *
 * Developed by Mr. Suhas Devmane, COMSC, Cardiff, UK
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Create notification channel on first launch
        createNotificationChannel()

        // Request notification permission for Android 13+
        requestNotificationPermission()

        enableEdgeToEdge()

        setContent {
            WattWiseTheme {
                val navController = rememberNavController()
                WattWiseNavGraph(navController = navController)
            }
        }
    }

    private fun requestNotificationPermission() {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            val permission = android.Manifest.permission.POST_NOTIFICATIONS
            if (checkSelfPermission(permission) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(permission), 101)
            }
        }
    }

    private fun createNotificationChannel() {
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
