package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PersonalSyncAutoWifiTest {
    private fun decide(
        transport: TelefonTransportArt = TelefonTransportArt.WIFI,
        transition: Boolean = true,
        active: Boolean = false,
        now: Long = 1_000_000L,
        last: Long = now - 60_000L,
        counter: Long = 8,
        lastCounter: Long = 8,
        own: Boolean = true,
        remoteOwn: Boolean = true,
        grant: Boolean = true
    ) = shouldStartPersonalSyncOnSecureWifi(transport, transition, true, own, remoteOwn,
        grant, active, now, last, counter, lastCounter)

    @Test fun `dirty while away starts immediately on authenticated wifi`() {
        assertTrue(decide(counter = 9))
    }

    @Test fun `unchanged reconnect inside debounce does not repeat`() {
        assertFalse(decide())
    }

    @Test fun `unchanged reconnect after debounce pulls remote`() {
        assertTrue(decide(last = 1_000_000L - 15 * 60_000L))
    }

    @Test fun `bluetooth secure connect never starts auto sync`() {
        assertFalse(decide(transport = TelefonTransportArt.BLUETOOTH, counter = 9))
    }

    @Test fun `unknown remote starts when organizer authenticates later in same wifi`() {
        assertTrue(decide(last = 0, lastCounter = -1))
    }

    @Test fun `active wifi only run and missing bilateral consent prevent storms`() {
        assertFalse(decide(active = true, counter = 9))
        assertFalse(decide(own = false, counter = 9))
        assertFalse(decide(remoteOwn = false, counter = 9))
        assertFalse(decide(grant = false, counter = 9))
        assertFalse(decide(transition = false, counter = 9))
    }
}
