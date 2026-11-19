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
import com.wattwise.userapp.util.AlertSelection
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.flow.first
import timber.log.Timber
import java.io.IOException

/**
 * Background alert check (no Firebase): about every 15 minutes, when the phone is
 * online, asks the server for the recent alerts of the signed-in account and shows a
 * phone notification for each one not shown before. Tapping it opens that alert.
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
        val bearer = secureTokenStore.getBearerHeader() ?: return Result.success()   // signed out
        return try {
            val response = apiService.getNotifications(bearerToken = bearer, limit = 30, unreadOnly = false)
            when {
                // Session expired or revoked: retrying cannot help. The app asks the user
                // to sign in again the next time it is opened.
                response.code() == 401 || response.code() == 403 -> Result.success()
                !response.isSuccessful -> Result.retry()
                else -> {
                    val items = response.body().orEmpty()
                    val lastSeen = notifPrefs.lastSeenNotificationId.first().toIntOrNull()
                    val selection = AlertSelection.select(
                        items.map { AlertSelection.Alert(it.id, it.isRead) }, lastSeen
                    )
                    val byId = items.associateBy { it.id }
                    selection.toShow.mapNotNull { byId[it] }.forEach { item ->
                        val type = when ((item.severity ?: "").uppercase()) {
                            "CRITICAL" -> "critical"
                            "WARNING"  -> "warning"
                            else       -> "info"
                        }
                        WattWiseFcmService.showNotification(
                            context = context,
                            title = item.title?.takeIf { it.isNotBlank() } ?: "WattWise alert",
                            body = item.message.orEmpty(),
                            type = type,
                            historyId = item.id.toString(),
                            dataBundle = Bundle().apply {
                                putString("notification_id", item.id.toString())
                                putString("tab", "notifications")
                            }
                        )
                    }
                    selection.newLastSeenId?.let { notifPrefs.setLastSeenNotificationId(it.toString()) }
                    Timber.d("Alert check: ${items.size} fetched, ${selection.toShow.size} shown")
                    Result.success()
                }
            }
        } catch (e: IOException) {
            Result.retry()                       // offline or server unreachable
        } catch (e: Exception) {
            Timber.e(e, "Alert check failed")
            Result.failure()                     // bad data or a bug: wait for the next period
        }
    }

    companion object {
        const val WORK_NAME = "wattwise_notification_poll"
    }
}
