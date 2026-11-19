package com.wattwise.userapp.util

import com.wattwise.userapp.util.AlertSelection.Alert
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AlertSelectionTest {

    @Test
    fun `nothing fetched changes nothing`() {
        val s = AlertSelection.select(emptyList(), 10)
        assertEquals(emptyList<Int>(), s.toShow)
        assertNull(s.newLastSeenId)
    }

    @Test
    fun `shows only alerts newer than the last one shown, oldest first`() {
        val s = AlertSelection.select(listOf(Alert(12, true), Alert(11, false), Alert(10, false), Alert(9, false)), 10)
        assertEquals(listOf(11, 12), s.toShow)       // read state is ignored: it was never shown on this phone
        assertEquals(12, s.newLastSeenId)
    }

    @Test
    fun `no new alerts leaves the marker alone`() {
        val s = AlertSelection.select(listOf(Alert(10, false), Alert(9, false)), 10)
        assertEquals(emptyList<Int>(), s.toShow)
        assertNull(s.newLastSeenId)
    }

    @Test
    fun `first run shows a few unread alerts, not the whole history`() {
        val alerts = (1..30).map { Alert(it, isRead = it % 2 == 0) }
        val s = AlertSelection.select(alerts, null)
        assertEquals(listOf(25, 27, 29), s.toShow)
        assertEquals(30, s.newLastSeenId)
    }

    @Test
    fun `first run with everything read shows nothing but sets the marker`() {
        val s = AlertSelection.select(listOf(Alert(5, true), Alert(4, true)), null)
        assertEquals(emptyList<Int>(), s.toShow)
        assertEquals(5, s.newLastSeenId)
    }

    @Test
    fun `a long backlog is capped to the newest alerts`() {
        val s = AlertSelection.select((1..30).map { Alert(it, false) }, 0)
        assertEquals(AlertSelection.MAX_PER_CYCLE, s.toShow.size)
        assertEquals(30, s.toShow.last())
        assertEquals(30, s.newLastSeenId)
    }
}
