package com.wattwise.userapp.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerUrlsTest {

    @Test
    fun `default ports add no suffix`() {
        assertEquals("http://67.207.68.22", ServerUrls.build("http://67.207.68.22", 80))
        assertEquals("http://67.207.68.22", ServerUrls.build("http://67.207.68.22/", 443))
        assertEquals("https://example.org", ServerUrls.build(" https://example.org ", 443))
    }

    @Test
    fun `custom port is appended once`() {
        assertEquals("http://192.168.1.5:3001", ServerUrls.build("http://192.168.1.5", 3001))
        assertEquals("http://192.168.1.5:3001", ServerUrls.build("http://192.168.1.5:3001", 8000))
    }

    @Test
    fun `blank address falls back to the default server`() {
        assertEquals(Constants.DEFAULT_SERVER_URL, ServerUrls.build("  ", 80))
        assertEquals(Constants.DEFAULT_SERVER_URL, ServerUrls.build(null, null))
    }

    @Test
    fun `only http and https addresses with a host are valid`() {
        assertTrue(ServerUrls.isValid("http://67.207.68.22"))
        assertTrue(ServerUrls.isValid("https://example.org/"))
        assertFalse(ServerUrls.isValid("67.207.68.22"))
        assertFalse(ServerUrls.isValid("http://"))
        assertFalse(ServerUrls.isValid("ftp://example.org"))
        assertFalse(ServerUrls.isValid("http://my server"))
    }
}
