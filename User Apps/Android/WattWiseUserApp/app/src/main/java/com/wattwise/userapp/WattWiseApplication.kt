package com.wattwise.userapp

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.wattwise.userapp.data.local.ServerPreferencesDataStore
import com.wattwise.userapp.di.ServerConfig
import com.wattwise.userapp.util.Constants
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import timber.log.Timber
import javax.inject.Inject

/**
 * WattWise Application class.
 * Initialises Hilt DI, Timber logging, notification channels, and loads the
 * user-saved server URL into [ServerConfig] so the first API call goes to the
 * right host.
 */
@HiltAndroidApp
class WattWiseApplication : Application() {

    @Inject lateinit var serverConfig: ServerConfig
    @Inject lateinit var serverPrefs: ServerPreferencesDataStore

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()

        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        }

        createNotificationChannels()

        // Load the user-saved server URL into ServerConfig so Retrofit uses it
        // from the very first request (login/signup) rather than the compile-time default.
        appScope.launch {
            val savedUrl = serverPrefs.serverUrl.first()
            serverConfig.baseUrl = savedUrl
            Timber.d("Server URL loaded: $savedUrl")
        }

        Timber.d("WattWise ${Constants.APP_VERSION} started")
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)

            manager.createNotificationChannel(
                NotificationChannel(
                    Constants.NOTIFICATION_CHANNEL_ID_ENERGY,
                    Constants.NOTIFICATION_CHANNEL_NAME_ENERGY,
                    NotificationManager.IMPORTANCE_HIGH
                ).apply {
                    description = "Alerts about your energy usage, goals, and peak tariff periods"
                    enableVibration(true)
                }
            )

            manager.createNotificationChannel(
                NotificationChannel(
                    Constants.NOTIFICATION_CHANNEL_ID_INFO,
                    Constants.NOTIFICATION_CHANNEL_NAME_INFO,
                    NotificationManager.IMPORTANCE_DEFAULT
                ).apply {
                    description = "WattWise daily summaries, tips, and achievements"
                    enableVibration(false)
                }
            )
        }
    }
}
