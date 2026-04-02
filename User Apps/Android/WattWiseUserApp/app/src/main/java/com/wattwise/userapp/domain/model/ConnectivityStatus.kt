package com.wattwise.userapp.domain.model

/**
 * Represents network connectivity state, observed as a Flow.
 */
sealed class ConnectivityStatus {
    data object Available : ConnectivityStatus()
    data object Unavailable : ConnectivityStatus()
    data object Losing : ConnectivityStatus()
    data object Lost : ConnectivityStatus()
}
