package io.gitlab.maik3531.magnolienotes.netz

import org.junit.Assert.*
import org.junit.Test

class LanTorTest {
    @Test fun apiTargetMatrix() {
        for (api in listOf(26, 28, 35, 36, 37, 38))
            for (target in listOf(35, 36, 37, 38))
                for (grant in listOf(false, true)) {
                    val tor = LanTor { !LanRegel.erforderlich(api, target) || grant }
                    assertEquals("api=$api target=$target grant=$grant", api < 37 || target < 37 || grant, tor.erlaubt())
                }
    }
    @Test fun denialAndBackgroundRestartStayQuiet() {
        var grant = false
        repeat(3) {
            val tor = LanTor { grant }
            repeat(30) { assertFalse(tor.erlaubt()) }
            var closed = false
            assertTrue(runCatching { tor.beobachten(AutoCloseable { closed = true }) }.isFailure)
            assertTrue(closed)
        }
        grant = true
        assertTrue(LanTor { grant }.erlaubt())
    }
    @Test fun revocationClosesOnlyRegisteredLanAndInvalidatesCallbacks() {
        var grant = true
        val tor = LanTor { grant }
        val token = tor.marke()
        var lanClosed = 0
        var bluetoothClosed = 0
        val bluetooth = AutoCloseable { bluetoothClosed++ }
        tor.beobachten(AutoCloseable { lanClosed++ })
        assertTrue(tor.aktuell(token))
        grant = false
        assertFalse(tor.erlaubt())
        assertFalse(tor.erlaubt())
        assertEquals(1, lanClosed)
        assertEquals(0, bluetoothClosed)
        grant = true
        assertTrue(tor.erlaubt())
        assertFalse(tor.aktuell(token))
        assertTrue(tor.aktuell(tor.marke()))
        bluetooth.close()
    }
    @Test fun completionUnregistersResource() {
        var grant = true
        val tor = LanTor { grant }
        var closed = false
        tor.beobachten(AutoCloseable { closed = true }).close()
        grant = false
        assertFalse(tor.erlaubt())
        assertFalse(closed)
    }
    @Test fun failingCloseDoesNotSkipOtherTransports() {
        var grant = true
        val tor = LanTor { grant }
        var closed = false
        tor.beobachten(AutoCloseable { error("synthetic") })
        tor.beobachten(AutoCloseable { closed = true })
        grant = false
        assertFalse(tor.erlaubt())
        assertTrue(closed)
    }
    @Test fun grantLostWhileRegisteringFailsClosed() {
        var calls = 0
        val tor = LanTor { ++calls == 1 }
        val token = tor.marke()
        var closed = false
        assertTrue(runCatching { tor.beobachten(AutoCloseable { closed = true }) }.isFailure)
        assertTrue(closed)
        assertFalse(tor.aktuell(token))
    }
    @Test fun absoluteLocalNameIsGuardedBeforeResolver() {
        var resolved = false
        val result = runCatching {
            LanRegel.ziel("printer.LOCAL.", { throw java.io.IOException("denied") }, {
                resolved = true
                java.net.InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1))
            })
        }
        assertTrue(result.exceptionOrNull() is java.io.IOException)
        assertFalse(resolved)
    }
}
