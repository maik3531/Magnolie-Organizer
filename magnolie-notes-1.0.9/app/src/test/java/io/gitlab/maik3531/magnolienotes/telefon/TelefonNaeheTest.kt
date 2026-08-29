package io.gitlab.maik3531.magnolienotes.telefon

import android.telephony.TelephonyManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TelefonNaeheTest {
    private class FakeLock : TelefonNaeheSperre {
        override var held = false
        var acquired = 0
        val releases = mutableListOf<Boolean>()

        override fun acquire() {
            acquired++
            held = true
        }

        override fun release(waitForNoProximity: Boolean) {
            releases += waitForNoProximity
            held = false
        }
    }

    @Test fun `Naeheresperre folgt nur einem aktiven Anruf`() {
        val lock = FakeLock()
        val proximity = TelefonNaehe(lock)

        proximity.update(TelephonyManager.CALL_STATE_RINGING)
        assertFalse(lock.held)
        proximity.update(TelephonyManager.CALL_STATE_OFFHOOK)
        proximity.update(TelephonyManager.CALL_STATE_OFFHOOK)
        assertTrue(lock.held)
        assertEquals(1, lock.acquired)
        proximity.update(TelephonyManager.CALL_STATE_IDLE)
        assertFalse(lock.held)
        assertEquals(listOf(true), lock.releases)
    }

    @Test fun `Dienstende gibt eine gehaltene Naeheresperre sicher frei`() {
        val lock = FakeLock()
        val proximity = TelefonNaehe(lock)

        proximity.update(TelephonyManager.CALL_STATE_OFFHOOK)
        proximity.stop(true)
        proximity.stop(true)
        assertEquals(listOf(true), lock.releases)
    }

    @Test fun `Klingeln nach aktivem Anruf gibt die Sperre am Sensor frei`() {
        val lock = FakeLock()
        val proximity = TelefonNaehe(lock)

        proximity.update(TelephonyManager.CALL_STATE_OFFHOOK)
        proximity.update(TelephonyManager.CALL_STATE_RINGING)
        proximity.update(TelephonyManager.CALL_STATE_RINGING)
        assertFalse(lock.held)
        assertEquals(listOf(true), lock.releases)
    }

    @Test fun `Lauscherbedarf bindet Dienst Berechtigung Freigabe und aktiven Anruf`() {
        assertFalse(telefonLauscherNoetig(false, true, true, true))
        assertFalse(telefonLauscherNoetig(true, false, true, true))
        assertFalse(telefonLauscherNoetig(true, true, false, false))
        assertTrue(telefonLauscherNoetig(true, true, true, false))
        assertTrue(telefonLauscherNoetig(true, true, false, true))
    }

    @Test fun `ausgehender Anruf ignoriert Idle nur bis zum ersten echten Zustand`() {
        assertTrue(telefonInitialesAusgehendesIdle(
            "outgoing", false, TelephonyManager.CALL_STATE_IDLE))
        assertFalse(telefonInitialesAusgehendesIdle(
            "outgoing", true, TelephonyManager.CALL_STATE_IDLE))
        assertFalse(telefonInitialesAusgehendesIdle(
            "incoming", false, TelephonyManager.CALL_STATE_IDLE))
        assertFalse(telefonInitialesAusgehendesIdle(
            "outgoing", false, TelephonyManager.CALL_STATE_OFFHOOK))
    }

    @Test fun `fehlender Naeherungssensor bleibt wirkungslos`() {
        val proximity = TelefonNaehe(null)
        proximity.update(TelephonyManager.CALL_STATE_OFFHOOK)
        proximity.update(TelephonyManager.CALL_STATE_IDLE)
        proximity.stop(false)
    }
}
