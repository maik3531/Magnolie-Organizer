package io.gitlab.maik3531.magnolienotes.daten

import java.time.Instant
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ZeitFeierabendIntegrationTest {
    private fun ms(time: String) = Instant.parse("2026-10-04T${time}Z").toEpochMilli()
    private fun started(alarm: ZeitFeierabendwecker) = ZeiterfassungStand(enabled = true,
        fixedPauses = listOf(ZeitPausenfenster(720, 750)), endAlarm = alarm,
        wifi = ZeitWlanAutomatik(enabled = true, ssid = "Synthetic workplace"))
        .start(Zeiteintrag(startMinute = ms("08:00:00") / 60000, zone = "UTC"))
    private fun restart(state: ZeiterfassungStand) = Json.decodeFromString(ZeiterfassungStand.serializer(),
        Json.encodeToString(ZeiterfassungStand.serializer(), state)).validate()

    @Test fun workTargetRechecksFixedBreaksInsteadOfFiringAtTheOriginalGrossEstimate() {
        var state = started(ZeitFeierabendwecker(workedMinutes = 480))
        val entry = state.entries.single()
        assertEquals(ms("16:00:00") / 60000, state.pauseRuns[entry.id]!!.nextEndAlarmMinute(entry, entry.startMinute))
        assertEquals(state, state.claimEndAlarm(entry.id, ms("16:00:00")))
        assertEquals(ms("16:30:00") / 60000, state.pauseRuns[entry.id]!!.nextEndAlarmMinute(entry, ms("16:00:00") / 60000))
        state = restart(state).claimEndAlarm(entry.id, ms("16:30:00"))
        assertNull(state.entries.single().endMinute)
        assertTrue(state.pauseRuns[entry.id]!!.endAlarm.fired)
        assertNull(state.pauseRuns[entry.id]!!.nextEndAlarmMinute(entry, ms("17:00:00") / 60000))
        assertEquals(state, restart(state).claimEndAlarm(entry.id, ms("17:00:00")))
    }

    @Test fun optionalAutomaticStopClosesThePauseAndDurablyBlocksWifiForOneHour() {
        var state = started(ZeitFeierabendwecker(clockMinute = 720, autoStop = true))
        state = state.pause(state.entries.single(), ms("11:55:17"))
        val id = state.entries.single().id
        state = restart(state).claimEndAlarm(id, ms("12:00:00"))
        assertEquals(ms("12:00:00") / 60000, state.entries.single().endMinute)
        assertEquals(5L, state.entries.single().pauseMinutes)
        assertEquals(ms("13:00:00"), state.wifi.blockedUntilMs)
        assertTrue(state.pauseRuns.isEmpty())
        assertEquals(state, restart(state).claimEndAlarm(id, ms("12:15:00")))
        assertEquals(state, state.startFromWifi(state.wifi.ssid, ms("12:59:00"), ms("12:59:00"), "late"))
        assertEquals(2, state.startFromWifi(state.wifi.ssid, ms("14:00:00"), ms("14:00:00"), "late").entries.size)
    }

    @Test fun grossHoursKeepAdvancingDuringManualPauseButNetHoursWaitForResume() {
        var net = started(ZeitFeierabendwecker(workedMinutes = 240))
        net = net.pause(net.entries.single(), ms("11:55:00"))
        val entry = net.entries.single()
        val run = net.pauseRuns[entry.id]!!
        assertNull(run.nextEndAlarmMinute(entry, ms("12:00:00") / 60000))
        assertEquals(ms("12:00:00") / 60000,
            run.copy(endAlarm = run.endAlarm.copy(includePauses = true)).nextEndAlarmMinute(entry, ms("12:00:00") / 60000))
        net = net.resume(entry, ms("12:10:00"))
        assertEquals(ms("12:15:00") / 60000,
            net.pauseRuns[entry.id]!!.nextEndAlarmMinute(net.entries.single(), ms("12:10:00") / 60000))
    }

    @Test fun laterPreferencesCannotChangeTheRunningGoalAndManualStopCancelsIt() {
        var state = started(ZeitFeierabendwecker(clockMinute = 960))
        state = state.copy(endAlarm = ZeitFeierabendwecker(clockMinute = 720, autoStop = true))
        val entry = state.entries.single()
        assertEquals(state, state.claimEndAlarm(entry.id, ms("12:00:00")))
        state = state.finish(entry, ms("13:00:00"))
        assertEquals(state, restart(state).claimEndAlarm(entry.id, ms("16:00:00")))
        assertTrue(state.pauseRuns.isEmpty())
    }

    @Test fun correctingAnOpenRecordsPauseTotalKeepsItsEndAlarmAndTheEditedBaseline() {
        val state = started(ZeitFeierabendwecker(workedMinutes = 480))
        val entry = state.entries.single()
        val edited = restart(state.replace(entry, entry.copy(pauseMinutes = 42)))
        assertEquals(42L, edited.projected(edited.entries.single(), ms("16:00:00") / 60000).pausedMinutes())
        assertEquals(ms("16:42:00") / 60000,
            edited.pauseRuns[entry.id]!!.nextEndAlarmMinute(edited.entries.single(), ms("16:00:00") / 60000))
        assertEquals(42L, edited.finish(edited.entries.single(), ms("17:00:00")).entries.single().pauseMinutes)
    }
}
