package com.wattwise.userapp.ui.settings

import com.wattwise.userapp.data.local.TokenDataStore
import com.wattwise.userapp.data.repository.ServerRepository
import com.wattwise.userapp.domain.model.Resource
import io.mockk.coEvery
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Unit tests for SettingsViewModel.
 * Demonstrates MockK, Coroutine TestDispatcher, and assertions.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var repository: ServerRepository
    private lateinit var tokenDataStore: TokenDataStore
    private lateinit var viewModel: SettingsViewModel

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        repository = mockk(relaxed = true)
        tokenDataStore = mockk(relaxed = true)

        // Stub reactive flows
        coEvery { repository.serverUrl } returns flowOf("https://www.talk2futurebuildings.systems")
        coEvery { repository.port } returns flowOf(443)
        coEvery { repository.timeout } returns flowOf(20)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `testConnection returns success on valid server`() = runTest(testDispatcher) {
        coEvery {
            repository.testConnection(any(), any())
        } returns Resource.Success(200)

        viewModel = SettingsViewModel(repository, tokenDataStore)
        viewModel.testConnection("https://www.talk2futurebuildings.systems", 443)

        advanceUntilIdle()

        val result = viewModel.testResult.value
        assertTrue("Expected Success", result is Resource.Success)
        assertEquals(200, (result as Resource.Success).data)
    }

    @Test
    fun `testConnection returns error on unreachable server`() = runTest(testDispatcher) {
        coEvery {
            repository.testConnection(any(), any())
        } returns Resource.Error("Connection refused")

        viewModel = SettingsViewModel(repository, tokenDataStore)
        viewModel.testConnection("http://invalid-server", 3001)

        advanceUntilIdle()

        val result = viewModel.testResult.value
        assertTrue("Expected Error", result is Resource.Error)
    }
}
