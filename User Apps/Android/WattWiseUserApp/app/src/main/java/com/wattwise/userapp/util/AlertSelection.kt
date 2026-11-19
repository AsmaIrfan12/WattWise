package com.wattwise.userapp.util

/**
 * Decides which alerts the background check shows as phone notifications.
 *
 * Kept free of Android classes so the rules are unit-tested:
 *  - normal run: every alert newer than the last one shown, oldest first, capped;
 *  - first run (fresh install or after sign-in): only a few UNREAD recent alerts, so
 *    the phone is not flooded with the whole history of the account;
 *  - the "last shown" marker always advances to the newest alert seen, shown or not.
 */
object AlertSelection {

    const val MAX_PER_CYCLE = 8
    const val MAX_FIRST_RUN = 3

    data class Alert(val id: Int, val isRead: Boolean)

    data class Selection(val toShow: List<Int>, val newLastSeenId: Int?)

    fun select(alerts: List<Alert>, lastSeenId: Int?): Selection {
        if (alerts.isEmpty()) return Selection(emptyList(), null)
        val newest = alerts.maxOf { it.id }
        if (lastSeenId == null) {
            val unread = alerts.filter { !it.isRead }.map { it.id }.sorted().takeLast(MAX_FIRST_RUN)
            return Selection(unread, newest)
        }
        val fresh = alerts.filter { it.id > lastSeenId }.map { it.id }.sorted().takeLast(MAX_PER_CYCLE)
        return Selection(fresh, if (newest > lastSeenId) newest else null)
    }
}
