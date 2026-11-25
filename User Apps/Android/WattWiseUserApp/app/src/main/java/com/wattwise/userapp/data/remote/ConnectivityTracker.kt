package com.wattwise.userapp.data.remote

import com.wattwise.userapp.domain.model.ConnectivityStatus

/**
 * Keeps count of the networks that are up, so "offline" is reported only when NONE is.
 *
 * A phone usually has two networks at once (Wi-Fi and mobile data). Android reports
 * each one separately, and reports a network as lost when the phone merely moves from
 * one to the other. Treating any single "lost" as "no internet" showed a red
 * "No internet connection" banner over a dashboard that was working.
 *
 * Plain Kotlin (no Android classes), so the rule is unit-tested. A network id is
 * whatever uniquely names a network; the observer passes Network.getNetworkHandle().
 */
class ConnectivityTracker {

    private val up = mutableSetOf<Long>()

    @Synchronized
    fun onAvailable(networkId: Long): ConnectivityStatus {
        up.add(networkId)
        return ConnectivityStatus.Available
    }

    /** A network is about to drop: only worth saying when it is the last one. */
    @Synchronized
    fun onLosing(networkId: Long): ConnectivityStatus =
        if ((up - networkId).isEmpty()) ConnectivityStatus.Losing else ConnectivityStatus.Available

    @Synchronized
    fun onLost(networkId: Long): ConnectivityStatus {
        up.remove(networkId)
        return if (up.isEmpty()) ConnectivityStatus.Lost else ConnectivityStatus.Available
    }

    @Synchronized
    fun isConnected(): Boolean = up.isNotEmpty()
}
