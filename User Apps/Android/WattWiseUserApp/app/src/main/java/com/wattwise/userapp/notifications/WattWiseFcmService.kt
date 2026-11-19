package com.wattwise.userapp.notifications

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.os.Bundle
import android.util.Log
import androidx.core.app.NotificationCompat
import com.wattwise.userapp.R
import com.wattwise.userapp.util.Constants

/**
 * WattWise Notification Service — Firebase-free stub.
 *
 * FCM/Google Services are disabled for this sideloaded build.
 * Push notifications will be re-enabled once google-services.json
 * is added and the Google Services plugin is restored.
 *
 * Local / server-triggered notifications can still be shown by
 * calling [showNotification] directly.
 *
 * Developer : Mr. Suhas Devmane, Cardiff University, UK
 * Version   : 4.0.0 (Community Release)
 */
object WattWiseFcmService {

    private const val TAG = "WattWiseNotif"
    private const val GROUP_ALERTS = "wattwise_alerts"
    private const val SUMMARY_ID = 0x57415454   // fixed id: one summary, updated in place

    /**
     * Android bundles several alerts under one header. Without our own summary, tapping
     * that header only opened the app on its home tab; this one opens the Alerts tab.
     */
    private fun postGroupSummary(context: Context, manager: NotificationManager) {
        val intent = WattWiseNotificationRouter.buildLaunchIntent(
            context, Bundle().apply { putString("tab", "notifications") }
        )
        val pending = PendingIntent.getActivity(
            context, SUMMARY_ID, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val summary = NotificationCompat.Builder(context, Constants.NOTIFICATION_CHANNEL_ID_INFO)
            .setSmallIcon(R.drawable.ic_notification_wattwise)
            .setContentTitle("WattWise alerts")
            .setContentText("Tap to see your alerts")
            .setGroup(GROUP_ALERTS)
            .setGroupSummary(true)
            .setGroupAlertBehavior(NotificationCompat.GROUP_ALERT_CHILDREN)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        manager.notify(SUMMARY_ID, summary)
    }

    /**
     * Display a system notification without FCM.
     * Call this from any component that receives a push payload via
     * WebSocket or polling once the app is open.
     */
    fun showNotification(
        context: Context,
        title: String,
        body: String,
        type: String = "info",
        historyId: String? = null,
        dataBundle: Bundle = Bundle()
    ) {
        val channelId = when (type) {
            "critical", "warning" -> Constants.NOTIFICATION_CHANNEL_ID_ENERGY
            else                  -> Constants.NOTIFICATION_CHANNEL_ID_INFO
        }

        val contentIntent = WattWiseNotificationRouter.buildLaunchIntent(context, dataBundle)
        val pendingIntent = PendingIntent.getActivity(
            context,
            historyId?.hashCode() ?: System.currentTimeMillis().toInt(),
            contentIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val priority = when (type) {
            "critical" -> NotificationCompat.PRIORITY_HIGH
            "warning"  -> NotificationCompat.PRIORITY_DEFAULT
            else       -> NotificationCompat.PRIORITY_LOW
        }

        val category = when (type) {
            "critical" -> NotificationCompat.CATEGORY_ALARM
            else       -> NotificationCompat.CATEGORY_RECOMMENDATION
        }

        val iconRes = R.drawable.ic_notification_wattwise

        val builder = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(iconRes)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(priority)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .setCategory(category)
            .setGroup(GROUP_ALERTS)

        if (type == "critical" || type == "opportunity") {
            val actionBundle = Bundle(dataBundle)
            actionBundle.putString("screen", "DeviceDetails")
            val actionIntent = WattWiseNotificationRouter.buildLaunchIntent(context, actionBundle)
            val actionPending = PendingIntent.getActivity(
                context,
                ("DeviceDetails" + System.currentTimeMillis()).hashCode(),
                actionIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            builder.addAction(0, "View Details", actionPending)
        }

        val notification = builder.build()
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val notifId = historyId?.hashCode() ?: System.currentTimeMillis().toInt()
        manager.notify(notifId, notification)
        postGroupSummary(context, manager)

        Log.d(TAG, "Notification displayed: id=$notifId channel=$channelId")
    }
}
