package com.wattwise.userapp.domain.model

/**
 * Generic sealed class representing the state of an asynchronous operation.
 * Used throughout the app for API responses, database queries, and connection tests.
 */
sealed class Resource<out T> {
    data class Success<T>(val data: T) : Resource<T>()
    data class Error(val message: String, val exception: Throwable? = null) : Resource<Nothing>()
    data object Loading : Resource<Nothing>()
}
