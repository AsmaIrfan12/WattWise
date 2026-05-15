package com.wattwise.userapp.di

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Process-wide hand-off for a pending deep-link tab.
 *
 * MainActivity receives notification-tap / URI intents, but it resolves
 * MainViewModel from a different ViewModelStore than the one MainScreen uses
 * (Activity store vs NavBackStackEntry store via hiltViewModel()). Routing the
 * tab through this @Singleton guarantees the value survives that scoping gap —
 * including a cold start where MainScreen's ViewModel doesn't exist yet when
 * the intent arrives.
 */
@Singleton
class DeepLinkBus @Inject constructor() {
    private val _pendingTab = MutableStateFlow<String?>(null)
    val pendingTab: StateFlow<String?> = _pendingTab.asStateFlow()

    fun publish(tab: String) {
        _pendingTab.value = tab
    }

    fun consume() {
        _pendingTab.value = null
    }
}
