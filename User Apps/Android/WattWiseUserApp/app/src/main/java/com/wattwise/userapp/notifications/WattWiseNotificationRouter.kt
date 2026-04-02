package com.wattwise.userapp.notifications

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log
import com.wattwise.userapp.util.Constants

/**
 * WattWise Push Notification Receiver
 * =====================================
 * Handles Expo push notification payloads received by the Android app.
 *
 * Registers a BroadcastReceiver that is called when the user taps a
 * WattWise notification. Parses the deep-link payload and routes to
 * the appropriate screen in the WebView dashboard.
 *
 * Notification data structure (from push-notification-services.js):
 *   {
 *     type: "critical" | "opportunity" | "info" | "warning",
 *     applianceKey: "dryer" | "kettle" | ...,
 *     deviceName: string,
 *     priority: "high" | "medium" | "low",
 *     historyId: string,
 *     notificationId: string,
 *     screen: "DeviceDetails"
 *   }
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
object WattWiseNotificationRouter {

    private const val TAG = "WattWiseNotifRouter"

    /**
     * Called when the user taps a WattWise push notification.
     * Extracts the deep-link data and returns a URL to load in the WebView.
     *
     * @param data Extra data from the notification intent
     * @param baseUrl The current server base URL (from Constants.DEFAULT_SERVER_URL)
     * @return URL string to navigate the WebView to, or null for default
     */
    fun resolveDeepLinkUrl(data: Bundle?, baseUrl: String = Constants.DEFAULT_SERVER_URL): String? {
        if (data == null) return null

        val type         = data.getString("type") ?: return null
        val applianceKey = data.getString("applianceKey") ?: return null
        val historyId    = data.getString("historyId")
        val screen       = data.getString("screen", "DeviceDetails")

        Log.d(TAG, "Resolving deep-link: type=$type applianceKey=$applianceKey screen=$screen")

        // Build deep-link URL for the user dashboard WebView
        return when (screen) {
            "DeviceDetails" -> "$baseUrl/device/$applianceKey?notification=$historyId&type=$type"
            "Notifications" -> "$baseUrl/notifications?highlight=$historyId"
            "Rankings"      -> "$baseUrl/rankings"
            "Goals"         -> "$baseUrl/goals"
            else            -> "$baseUrl/dashboard"
        }
    }

    /**
     * Map notification type to a user-friendly label for logging/analytics.
     */
    fun getTypeLabel(type: String): String = when (type) {
        "critical"    -> "⚠️ Critical Energy Alert"
        "opportunity" -> "💡 Energy Saving Opportunity"
        "warning"     -> "🟧 Energy Warning"
        "info"        -> "ℹ️ Energy Info"
        else          -> "⚡ WattWise Alert"
    }

    /**
     * Cancel a notification by its historyId (parsed from push payload).
     */
    fun cancelNotification(context: Context, notificationId: String) {
        try {
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            // Use hash of historyId as int ID for cancel
            manager.cancel(notificationId.hashCode())
            Log.d(TAG, "Cancelled notification: $notificationId")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to cancel notification: $e")
        }
    }

    /**
     * Build an Intent that opens the WattWise app + navigates the WebView
     * to the relevant screen based on the notification payload.
     *
     * Intended use: PendingIntent in the notification builder.
     */
    fun buildLaunchIntent(context: Context, data: Bundle?): Intent {
        // Launch the main activity; it will pick up the URL from the intent extras
        val intent = Intent(context, Class.forName("com.wattwise.userapp.MainActivity"))
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        val deepLinkUrl = resolveDeepLinkUrl(data)
        if (deepLinkUrl != null) {
            intent.putExtra("deep_link_url", deepLinkUrl)
        }
        return intent
    }
}
