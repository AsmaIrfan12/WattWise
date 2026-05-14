package com.wattwise.userapp

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.wattwise.userapp.data.local.ServerPreferencesDataStore
import com.wattwise.userapp.di.ServerConfig
import com.wattwise.userapp.util.Constants
import com.wattwise.userapp.workers.NotificationPollWorker
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import timber.log.Timber
import java.util.concurrent.TimeUnit
import javax.inject.Inject

/**
 * WattWise Application class.
 *
 * Initialises:
 *  - Hilt DI
 *  - Timber logging
 *  - Notification channels (Energy Alerts + Info)
 *  - User-saved server URL into [ServerConfig]
 *  - WorkManager background notification polling worker (15-min, FCM fallback)
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@HiltAndroidApp
class WattWiseApplication : Application(), Configuration.Provider {

    @Inject lateinit var serverConfig: ServerConfig
    @Inject lateinit var serverPrefs: ServerPreferencesDataStore
    @Inject lateinit var workerFactory: HiltWorkerFactory

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    // ── WorkManager Configuration ─────────────────────────────────────────
    // Use HiltWorkerFactory so @HiltWorker injection works in the polling worker.
    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .setMinimumLoggingLevel(
                if (BuildConfig.DEBUG) android.util.Log.DEBUG else android.util.Log.ERROR
            )
            .build()

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

        enqueueNotificationPolling()

        Timber.d("WattWise ${Constants.APP_VERSION} started")
    }

    // ── Background Notification Polling ───────────────────────────────────
    private fun enqueueNotificationPolling() {
        val request = PeriodicWorkRequestBuilder<NotificationPollWorker>(
            repeatInterval = 15,
            repeatIntervalTimeUnit = TimeUnit.MINUTES
        ).build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            NotificationPollWorker.WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,   // Don't restart if already scheduled
            request
        )
        Timber.d("⏱ NotificationPollWorker enqueued (15-min interval)")
    }

    // ── Notification Channels ─────────────────────────────────────────────
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
