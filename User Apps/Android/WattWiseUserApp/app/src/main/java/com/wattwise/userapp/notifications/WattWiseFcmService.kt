package com.wattwise.userapp.notifications

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.os.Bundle
import android.util.Log
import androidx.core.app.NotificationCompat
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

        // Use a built-in system drawable until a custom ic_notification_wattwise
        // drawable resource is added to res/drawable/
        val iconRes = android.R.drawable.ic_dialog_info

        val builder = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(iconRes)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(priority)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .setCategory(category)

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

        Log.d(TAG, "Notification displayed: id=$notifId channel=$channelId")
    }
}
