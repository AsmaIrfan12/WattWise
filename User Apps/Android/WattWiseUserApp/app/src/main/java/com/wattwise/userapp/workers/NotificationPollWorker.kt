package com.wattwise.userapp.workers

import android.content.Context
import android.os.Bundle
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.wattwise.userapp.data.local.NotificationPrefsStore
import com.wattwise.userapp.data.local.SecureTokenStore
import com.wattwise.userapp.data.remote.WattWiseApiService
import com.wattwise.userapp.notifications.WattWiseFcmService
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.flow.firstOrNull
import timber.log.Timber

/**
 * Background notification polling worker — FCM fallback.
 *
 * Runs every 15 minutes via [PeriodicWorkRequest]. Calls
 * GET /api/notifications/history?limit=20&unread_only=true
 * and fires a local system notification for any item newer than the
 * last-seen notification ID stored in [NotificationPrefsStore].
 *
 * This provides push-like behaviour without requiring Firebase / google-services.json.
 * Once FCM is wired up this worker can be disabled.
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
@HiltWorker
class NotificationPollWorker @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted workerParams: WorkerParameters,
    private val apiService: WattWiseApiService,
    private val secureTokenStore: SecureTokenStore,
    private val notifPrefs: NotificationPrefsStore
) : CoroutineWorker(context, workerParams) {

    override suspend fun doWork(): Result {
        return try {
            val bearer = secureTokenStore.getBearerHeader()
            if (bearer.isNullOrBlank()) {
                Timber.d("⏭ NotificationPollWorker: no auth token — skipping")
                return Result.success()
            }

            val response = apiService.getNotifications(
                bearerToken = bearer,
                limit = 20,
                unreadOnly = true
            )

            if (!response.isSuccessful) {
                Timber.w("NotificationPollWorker: API error ${response.code()}")
                return Result.retry()
            }

            val items = response.body() ?: emptyList()
            if (items.isEmpty()) {
                Timber.d("✅ NotificationPollWorker: no new notifications")
                return Result.success()
            }

            val lastSeenId = notifPrefs.lastSeenNotificationId.firstOrNull() ?: ""
            val lastSeenInt = lastSeenId.toIntOrNull() ?: 0

            // Filter to only items we haven't already shown
            val newItems = items.filter { it.id > lastSeenInt }
            Timber.d("NotificationPollWorker: ${items.size} fetched, ${newItems.size} new")

            // Show native system notification for each new item (newest first)
            newItems.sortedByDescending { it.id }.take(3).forEach { item ->
                val type = when (item.severity.uppercase()) {
                    "CRITICAL" -> "critical"
                    "WARNING"  -> "warning"
                    else       -> "info"
                }

                val extras = Bundle().apply {
                    putString("notification_id", item.id.toString())
                    putString("screen", "notifications")
                    putString("tab", "notifications")
                }

                WattWiseFcmService.showNotification(
                    context = context,
                    title = item.title,
                    body = item.message,
                    type = type,
                    historyId = item.id.toString(),
                    dataBundle = extras
                )
            }

            // Persist the highest ID seen so we don't re-notify next cycle
            val maxId = newItems.maxOfOrNull { it.id }?.toString()
            if (maxId != null) {
                notifPrefs.setLastSeenNotificationId(maxId)
                Timber.i("NotificationPollWorker: last seen ID updated → $maxId")
            }

            Result.success()

        } catch (e: Exception) {
            Timber.e(e, "NotificationPollWorker: unexpected error")
            Result.retry()
        }
    }

    companion object {
        const val WORK_NAME = "wattwise_notification_poll"
    }
}
