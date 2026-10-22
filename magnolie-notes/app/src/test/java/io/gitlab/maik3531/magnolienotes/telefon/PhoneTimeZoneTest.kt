package io.gitlab.maik3531.magnolienotes.telefon

import java.util.UUID
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PhoneTimeZoneTest {
    @Test fun ownPhoneClockDoesNotNeedContactOrIdentifierPermission() {
        val peer = TelefonPeer("computer", "Computer", "key", own_device = true, remote_own_device = true,
            device_status_granted = true, remote_device_status_granted = true, remote_device_status_available = true,
            remote_device_status_versions = listOf(1, 12))
        assertTrue(PhoneTimeZone.allowed(peer))
        for (blocked in listOf(peer.copy(own_device = false), peer.copy(remote_own_device = false),
            peer.copy(device_status_granted = false), peer.copy(remote_device_status_granted = false),
            peer.copy(remote_device_status_available = false), peer.copy(remote_device_status_versions = listOf(1, 3)),
            peer.copy(state = "paired_unverified"))) assertFalse(PhoneTimeZone.allowed(blocked))
    }

    @Test fun exactReadOnlyWireReportsOnlyTheActualNamedZone() {
        val id = UUID.randomUUID().toString()
        val request = buildJsonObject { put("request_id", id); put("version", 12) }
        PhoneTimeZone.validateRequest(request)
        TelefonNachrichten.validate(TelefonNachrichten.message("device_status.request", request, 60000))
        val report = PhoneTimeZone.report(id, "Asia/Tokyo", 1700000000000)
        PhoneTimeZone.validateReport(report)
        assertEquals(setOf("version", "request_id", "state", "time_zone", "captured_ms"), report.keys)
        assertEquals("Asia/Tokyo", report.string("time_zone"))
        assertEquals("available", report.string("state"))
        val unknown = PhoneTimeZone.report(id, "GMT+05:30", 1700000000000)
        PhoneTimeZone.validateReport(unknown)
        assertEquals("unavailable", unknown.string("state")); assertEquals("", unknown.string("time_zone"))
        for (bad in listOf(JsonObject(report + ("time_zone" to JsonPrimitive("Mars/Olympus"))),
            JsonObject(report + ("captured_ms" to JsonPrimitive("1700000000000"))),
            JsonObject(report + ("latitude" to JsonPrimitive(1.0)))))
            assertTrue(runCatching { PhoneTimeZone.validateReport(bad) }.isFailure)
        assertTrue(runCatching { PhoneTimeZone.validateRequest(JsonObject(request + ("write" to JsonPrimitive(true)))) }.isFailure)
        assertTrue(12 in TelefonCapabilities.phase1().getValue("device_status").versions)
        assertFalse(12 in TelefonCapabilities.phase1().getValue("personal_notes_sync").versions)
    }
}
