package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import kotlinx.serialization.json.*
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class TimeSyncProtokollTest {
    private fun settings(enabled: Boolean = true, revision: Long = 1) = buildJsonObject {
        put("format", 7); put("scope", "time_tracking"); put("enabled", enabled)
        put("revision", revision); put("epoch", UUID.randomUUID().toString())
    }
    private fun request(local: JsonObject, remote: JsonObject) = buildJsonObject {
        put("format", 7); put("trigger", "manual")
        put("sender_epoch", remote.getValue("epoch")); put("receiver_epoch", local.getValue("epoch"))
        put("sender_revision", remote.getValue("revision")); put("receiver_revision", local.getValue("revision"))
    }

    @Test fun bothOwnDevicesFreshNegotiationAndBothCurrentConsentsAreRequired() {
        val local = settings(); val remote = settings(); val body = request(local, remote)
        TimeSyncProtokoll.validate(TimeSyncProtokoll.REQUEST, body, true)
        assertTrue(TimeSyncProtokoll.allowed(body, local, remote, true, true, true, listOf(7), listOf(7)))
        assertFalse(TimeSyncProtokoll.allowed(body, local, remote, true, true, false, listOf(7), listOf(7)))
        assertFalse(TimeSyncProtokoll.allowed(body, local, remote, false, true, true, listOf(7), listOf(7)))
        assertFalse(TimeSyncProtokoll.allowed(body, local, remote, true, false, true, listOf(7), listOf(7)))
        assertFalse(TimeSyncProtokoll.allowed(body, local, remote, true, true, true, listOf(7), listOf(6)))
        assertFalse(TimeSyncProtokoll.allowed(body, settings(false, 2), remote, true, true, true, listOf(7), listOf(7)))
        val renewed = settings(true, 3)
        assertFalse(TimeSyncProtokoll.allowed(body, renewed, remote, true, true, true, listOf(7), listOf(7)))
    }

    @Test fun consentReplayCannotRollBackOrReuseAnEpoch() {
        val first = settings()
        assertEquals(first, TimeSyncProtokoll.acceptSettings(first, first))
        val next = settings(revision = 2)
        assertEquals(next, TimeSyncProtokoll.acceptSettings(first, next))
        assertThrows(IllegalArgumentException::class.java) { TimeSyncProtokoll.acceptSettings(next, first) }
        val reused = JsonObject(next + ("epoch" to first.getValue("epoch")))
        assertThrows(IllegalArgumentException::class.java) { TimeSyncProtokoll.acceptSettings(first, reused) }
    }

    @Test fun recordsAreStrictAndLocalRemovalIsNotAWireDeletion() {
        val record = ZeiterfassungStand(enabled = true).replace(null,
            Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC")).entries.single()
        val body = JsonObject(request(settings(), settings()) + ("entries" to TimeSyncProtokoll.encodeRecords(listOf(record))))
        TimeSyncProtokoll.validate(TimeSyncProtokoll.BATCH, body, true)
        assertEquals(listOf(record), TimeSyncProtokoll.decodeRecords(body))
        assertThrows(IllegalArgumentException::class.java) { TimeSyncProtokoll.encodeRecords(listOf(record.copy(deleted = true))) }
        val raw = body.getValue("entries").jsonArray.single().jsonObject
        val malformed = JsonObject(raw + ("startMinute" to JsonPrimitive("1000")))
        assertThrows(IllegalStateException::class.java) {
            TimeSyncProtokoll.validate(TimeSyncProtokoll.BATCH, JsonObject(body + ("entries" to JsonArray(listOf(malformed)))), true)
        }
    }

    @Test fun calendarProjectionCanOnlyArriveFromOrganizer() {
        val calendar = buildJsonObject {
            put("enabled", false); put("country", "DE"); put("regions", JsonArray(emptyList())); put("holidays", JsonArray(emptyList()))
        }
        val body = JsonObject(request(settings(), settings()) + mapOf("entries" to JsonArray(emptyList()), "calendar" to calendar))
        TimeSyncProtokoll.validate(TimeSyncProtokoll.BATCH, body, true)
        assertThrows(IllegalArgumentException::class.java) { TimeSyncProtokoll.validate(TimeSyncProtokoll.BATCH, body, false) }
    }

    @Test fun onlyOrganizerCanSendContentFreeDeletionMarkers() {
        val tombstone = Zeiteintrag(startMinute = 0, endMinute = 0, zone = "UTC", deleted = true,
            clock = mapOf(UUID.randomUUID().toString() to 1L))
        val body = JsonObject(request(settings(), settings()) +
            ("entries" to TimeSyncProtokoll.encodeRecords(listOf(tombstone), fromOrganizer = true)))
        TimeSyncProtokoll.validate(TimeSyncProtokoll.BATCH, body, true)
        assertThrows(IllegalArgumentException::class.java) { TimeSyncProtokoll.validate(TimeSyncProtokoll.BATCH, body, false) }
        assertThrows(IllegalArgumentException::class.java) { TimeSyncProtokoll.encodeRecords(listOf(tombstone)) }
        assertThrows(IllegalArgumentException::class.java) {
            TimeSyncProtokoll.encodeRecords(listOf(tombstone.copy(note = "Removed private contents")), fromOrganizer = true)
        }
    }

    @Test fun packetsPreserveEveryRecordAndRespectBothWireLimits() {
        val actor = UUID.randomUUID().toString()
        val records = (1..65).map { Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC",
            clock = mapOf(actor to 1L), note = "Synthetic") }
        val local = TimeSyncProtokoll.newSettings(true)
        val remote = TimeSyncProtokoll.newSettings(true)
        val ordinary = TimeSyncProtokoll.batches(local, remote, records)
        assertEquals(listOf(32, 32, 1), ordinary.map { it.getValue("entries").jsonArray.size })
        assertEquals(records, ordinary.flatMap { TimeSyncProtokoll.decodeRecords(it) })
        val unicode = records.map { it.copy(note = "😀".repeat(10000)) }
        val packets = TimeSyncProtokoll.batches(local, remote, unicode)
        assertTrue(packets.size > ordinary.size)
        assertEquals(unicode, packets.flatMap { TimeSyncProtokoll.decodeRecords(it) })
        packets.forEach {
            assertTrue(TelefonKanonisch.bytes(it).size <= TimeSyncProtokoll.MAX_BODY)
            TimeSyncProtokoll.validate(TimeSyncProtokoll.BATCH, it, fromOrganizer = false)
            TelefonNachrichten.validate(TelefonNachrichten.message(TimeSyncProtokoll.BATCH, it, 60000))
        }
        assertThrows(IllegalArgumentException::class.java) {
            TimeSyncProtokoll.batches(local, remote, listOf(records.first(), records.first()))
        }
    }

    @Test fun timeSessionRequiresFreshControlsButNotNoteImportConsent() {
        val local = settings(); val remote = settings()
        val session = PersonalNoteSession()
        session.timeSent = local; session.timeReceived = remote
        assertFalse(session.timeReady(local, remote))
        session.capabilitiesReceived = true; session.grantsReceived = true
        assertFalse(session.timeReady(local, remote))
        session.ownSettingsReceived = true
        assertTrue(session.timeReady(local, remote))
        assertFalse(session.ready(null, null))
        assertFalse(session.timeReady(settings(false, 2), remote))
        assertFalse(session.timeReady(local, settings(true, 2)))
        assertFalse(PersonalNoteSession().timeReady(local, remote))
    }
}
