package io.gitlab.maik3531.magnolienotes.daten

import java.time.Instant
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ZeitFeierabendweckerTest {
    private fun minute(value: String) = Instant.parse(value).epochSecond / 60

    @Test fun workDurationExcludesRecordedBreaksAndDoesNotStopTracking() {
        val start = minute("2026-10-04T08:00:00Z")
        val entry = Zeiteintrag(startMinute = start, pauseMinutes = 45, zone = "UTC")
        val alarm = ZeitFeierabendwecker(workedMinutes = 480)
        assertFalse(alarm.due(entry, start + 524))
        assertTrue(alarm.due(entry, start + 525))
        val fired = alarm.markFired(entry, start + 525)
        assertFalse(fired.due(entry, start + 600))
        assertNull(entry.endMinute)
        assertFalse(ZeitFeierabendwecker().due(entry, start + 1000))
    }

    @Test fun ongoingPauseDoesNotAdvanceTheWorkTarget() {
        val start = minute("2026-10-04T08:00:00Z")
        val entry = Zeiteintrag(startMinute = start, pauseMinutes = 45, zone = "UTC").pause(start + 480)
        val alarm = ZeitFeierabendwecker(workedMinutes = 480)
        assertFalse(alarm.due(entry, start + 540))
        assertFalse(alarm.due(entry, start + 600))
    }

    @Test fun optionalElapsedHoursIncludePausesButKeepTheOriginalTrackingStart() {
        val start = minute("2026-10-04T08:00:00Z")
        val entry = Zeiteintrag(startMinute = start, pauseMinutes = 45, zone = "UTC")
        val inclusive = ZeitFeierabendwecker(workedMinutes = 480, includePauses = true)
        assertFalse(inclusive.due(entry, start + 479))
        assertTrue(inclusive.due(entry, start + 480))
        assertTrue(inclusive.due(entry.pause(start + 400), start + 480))
        assertFalse(inclusive.copy(includePauses = false).due(entry, start + 480))
        assertTrue(inclusive.copy(includePauses = false).due(entry, start + 525))
    }

    @Test fun clockChoiceHandlesNightShiftsAndEarlyFinishCancels() {
        val start = minute("2026-10-04T22:00:00Z")
        val entry = Zeiteintrag(startMinute = start, zone = "UTC")
        val alarm = ZeitFeierabendwecker(clockMinute = 6 * 60)
        assertEquals(minute("2026-10-05T06:00:00Z"), alarm.clockDue(entry))
        assertFalse(alarm.due(entry, start + 479))
        assertTrue(alarm.due(entry, start + 480))
        assertFalse(alarm.due(entry.finish(start + 300), start + 480))
        val restored = Json.decodeFromString(ZeitFeierabendwecker.serializer(),
            Json.encodeToString(ZeitFeierabendwecker.serializer(), alarm.markFired(entry, start + 480)))
        assertFalse(restored.due(entry, start + 500))
    }
}
