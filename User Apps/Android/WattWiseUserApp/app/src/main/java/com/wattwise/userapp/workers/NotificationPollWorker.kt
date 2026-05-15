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

            // Fetch recent notifications regardless of server-side read state.
            // Dedup is driven solely by the locally-tracked last-seen ID — if we
            // filtered on unread_only, an alert marked read elsewhere (e.g. the
            // web dashboard) before this 15-min cycle would never be surfaced.
            val response = apiService.getNotifications(
                bearerToken = bearer,
                limit = 30,
                unreadOnly = false
            )

            if (!response.isSuccessful) {
                Timber.w("NotificationPollWorker: API error ${response.code()}")
                return Result.retry()
            }

            val items = response.body() ?: emptyList()
            if (items.isEmpty()) {
                Timber.d("✅ NotificationPollWorker: no notifications")
                return Result.success()
            }

            val lastSeenId = notifPrefs.lastSeenNotificationId.firstOrNull() ?: ""
            val lastSeenInt = lastSeenId.toIntOrNull() ?: 0

            // Everything newer than the last ID we surfaced. Show oldest→newest
            // so the status bar ordering is chronological and we never silently
            // drop a backlog (cap is a safety valve, not normal-path truncation).
            val newItems = items
                .filter { it.id > lastSeenInt }
                .sortedBy { it.id }
                .takeLast(MAX_NOTIFICATIONS_PER_CYCLE)
            Timber.d("NotificationPollWorker: ${items.size} fetched, ${newItems.size} new")

            newItems.forEach { item ->
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

        // Coalesce cap so a long offline backlog can't spam the status bar.
        // Energy nudges are low-volume; in normal operation a 15-min cycle
        // yields far fewer than this, so it never truncates the happy path.
        private const val MAX_NOTIFICATIONS_PER_CYCLE = 15
    }
}
