package com.wattwise.userapp.data.remote

import com.wattwise.userapp.domain.model.ConnectivityStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectivityTrackerTest {

    private val wifi = 101L
    private val mobile = 102L

    @Test
    fun `losing one of two networks is not offline`() {
        val t = ConnectivityTracker()
        t.onAvailable(wifi)
        t.onAvailable(mobile)
        assertEquals(ConnectivityStatus.Available, t.onLost(mobile))
        assertTrue(t.isConnected())
    }

    @Test
    fun `moving from wifi to mobile data never reports offline`() {
        val t = ConnectivityTracker()
        t.onAvailable(wifi)
        assertEquals(ConnectivityStatus.Available, t.onAvailable(mobile))   // mobile comes up first
        assertEquals(ConnectivityStatus.Available, t.onLosing(wifi))
        assertEquals(ConnectivityStatus.Available, t.onLost(wifi))          // then wifi goes
        assertTrue(t.isConnected())
    }

    @Test
    fun `losing the only network is offline`() {
        val t = ConnectivityTracker()
        t.onAvailable(wifi)
        assertEquals(ConnectivityStatus.Losing, t.onLosing(wifi))
        assertEquals(ConnectivityStatus.Lost, t.onLost(wifi))
        assertFalse(t.isConnected())
    }

    @Test
    fun `coming back after being offline is available again`() {
        val t = ConnectivityTracker()
        t.onAvailable(wifi)
        t.onLost(wifi)
        assertEquals(ConnectivityStatus.Available, t.onAvailable(mobile))
        assertTrue(t.isConnected())
    }

    @Test
    fun `a repeated or unknown loss changes nothing while another network is up`() {
        val t = ConnectivityTracker()
        t.onAvailable(wifi)
        assertEquals(ConnectivityStatus.Available, t.onLost(mobile))        // never seen coming up
        assertEquals(ConnectivityStatus.Available, t.onLost(mobile))
        assertTrue(t.isConnected())
    }
}
