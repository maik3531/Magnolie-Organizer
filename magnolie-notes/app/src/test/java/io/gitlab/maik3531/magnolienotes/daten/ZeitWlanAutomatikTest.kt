package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.Json
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class ZeitWlanAutomatikTest {
    @Test fun observationDoesNotRequireAConnectionAndDoesNotRestartAnActiveRecord() {
        val settings = ZeitWlanAutomatik(true, "Synthetic workplace")
        assertTrue(settings.canStart("Synthetic workplace", 1000, 1000, false, true))
        assertFalse(settings.canStart("Synthetic workplace", 1000, 1000, true, true))
        assertFalse(settings.canStart("Different WLAN", 1000, 1000, false, true))
        assertFalse(settings.canStart("Synthetic workplace", 1000, 200000, false, true))
        assertFalse(settings.canStart("Synthetic workplace", 1000, 1000, false, false))
    }

    @Test fun anyStopBlocksNewWifiStartsForOneHourByDefaultAcrossRestart() {
        val settings = ZeitWlanAutomatik(true, "Synthetic workplace")
        val id = UUID.randomUUID().toString()
        val stop = 1000000L
        val blocked = settings.afterStop(id, stop)
        val restored = Json.decodeFromString(ZeitWlanAutomatik.serializer(), Json.encodeToString(ZeitWlanAutomatik.serializer(), blocked))
        val until = stop + 60 * 60 * 1000
        assertFalse(restored.canStart(settings.ssid, until - 1, until - 1, false, true))
        assertFalse(restored.canStart(settings.ssid, stop, until, false, true))
        assertTrue(restored.canStart(settings.ssid, until, until, false, true))
        assertEquals(blocked, blocked.afterStop(id, until))
    }

    @Test fun splitShiftCanStartAgainOnReturnAtFourteenAfterAutomaticStopAtNoon() {
        val noon = java.time.Instant.parse("2026-10-04T12:00:00Z").toEpochMilli()
        val afternoon = noon + 2 * 60 * 60 * 1000
        val settings = ZeitWlanAutomatik(true, "Synthetic workplace")
            .afterStop(UUID.randomUUID().toString(), noon)
        assertFalse(settings.canStart(settings.ssid, noon + 59 * 60000, noon + 59 * 60000, false, true))
        assertTrue(settings.canStart(settings.ssid, afternoon, afternoon, false, true))
        assertFalse(settings.canStart(settings.ssid, afternoon + 60000, afternoon + 60000, true, true))
    }

    @Test fun blockingDurationIsConfigurableAndIndependentOfStartOrStopMode() {
        val stop = 1000000L
        val id = UUID.randomUUID().toString()
        val settings = ZeitWlanAutomatik(true, "Synthetic workplace", cooldownMinutes = 90).afterStop(id, stop)
        assertFalse(settings.canStart(settings.ssid, stop + 89 * 60000, stop + 89 * 60000, false, true))
        assertTrue(settings.canStart(settings.ssid, stop + 90 * 60000, stop + 90 * 60000, false, true))
        val disabled = ZeitWlanAutomatik().afterStop(id, stop)
        assertEquals(stop + 60 * 60000, disabled.blockedUntilMs)
    }

    @Test fun actualRecordTransitionsPreventDuplicateStartsAndManualFinishBlocksWifi() {
        val now = System.currentTimeMillis()
        val state = ZeiterfassungStand(enabled = true, wifi = ZeitWlanAutomatik(true, "Synthetic workplace"))
        val started = state.startFromWifi(state.wifi.ssid, now, now, "Synthetic activity")
        assertEquals(1, started.entries.size)
        assertEquals(started, started.startFromWifi(state.wifi.ssid, now + 1, now + 1, "Synthetic activity"))
        val record = started.entries.single()
        val finished = started.replace(record, record.finish(record.startMinute + 1))
        assertTrue(finished.wifi.blockedUntilMs >= now + 60 * 60000)
        assertEquals(finished, finished.startFromWifi(state.wifi.ssid, now + 60000, now + 60000, "Synthetic activity"))
        val manual = finished.start(Zeiteintrag(startMinute = record.startMinute + 2))
        assertEquals(2, manual.entries.size)
    }

    @Test fun stoppingARestoredOpenRecordIsANewEventRatherThanAReplayOfItsEarlierRemoval() {
        val start = 1800000000000L
        var state = ZeiterfassungStand(enabled = true).start(Zeiteintrag(startMinute = start / 60000))
        state = state.removeLocal(state.entries, start + 60000)
        val oldDeadline = state.wifi.blockedUntilMs
        state = state.restoreLocal(state.trash.single().id, start + 120000)
        state = state.finish(state.entries.single(), start + 180000)
        assertTrue(state.wifi.blockedUntilMs > oldDeadline)
        assertEquals(start + 180000 + 60 * 60000, state.wifi.blockedUntilMs)
        assertEquals(state.wifi, state.wifi.afterStop(state.entries.single().id, start + 900000))
    }
}
