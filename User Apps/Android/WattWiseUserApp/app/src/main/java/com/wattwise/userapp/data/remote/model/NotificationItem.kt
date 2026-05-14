package com.wattwise.userapp.data.remote.model

import com.google.gson.annotations.SerializedName

/**
 * Maps the WattWise backend notification JSON shape.
 *
 * Backend endpoint: GET /api/notifications/history
 * Example response item:
 * {
 *   "id": 42,
 *   "title": "High Consumption Alert",
 *   "message": "Your kettle used 3x its baseline.",
 *   "notification_type": "HIGH_CONSUMPTION",
 *   "severity": "WARNING",
 *   "is_read": false,
 *   "created_at": "2026-05-14T16:00:00Z"
 * }
 *
 * Developer: Mr. Suhas Devmane, Cardiff University, UK
 */
data class NotificationItem(
    @SerializedName("id")                val id: Int,
    @SerializedName("title")             val title: String,
    @SerializedName("message")           val message: String,
    @SerializedName("notification_type") val type: String = "INFO",
    @SerializedName("severity")          val severity: String = "INFO",
    @SerializedName("is_read")           val isRead: Boolean = false,
    @SerializedName("created_at")        val createdAt: String = "",
    @SerializedName("action_type")       val actionType: String? = null,
    @SerializedName("device_name")       val deviceName: String? = null
)
