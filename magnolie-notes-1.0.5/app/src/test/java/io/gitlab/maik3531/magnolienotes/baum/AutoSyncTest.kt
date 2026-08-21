package io.gitlab.maik3531.magnolienotes.baum

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AutoSyncTest {
    @Test
    fun `nur WLAN im laufenden Dienst und nach sechs Stunden synchronisiert`() {
        val jetzt = AutoSync.ABSTAND_MS * 2
        assertTrue(AutoSync.sollLaufen(true, true, true, 0, jetzt, true))
        assertFalse(AutoSync.sollLaufen(true, true, false, 0, jetzt, true))
        assertFalse(AutoSync.sollLaufen(true, false, true, 0, jetzt, true))
        assertFalse(AutoSync.sollLaufen(true, true, true, jetzt - 1_000, jetzt, true))
        assertFalse(AutoSync.sollLaufen(false, true, true, 0, jetzt, true))
    }
}
