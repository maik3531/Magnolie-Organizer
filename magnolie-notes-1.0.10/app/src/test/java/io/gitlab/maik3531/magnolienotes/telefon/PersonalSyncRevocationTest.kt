package io.gitlab.maik3531.magnolienotes.telefon

import java.io.File
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PersonalSyncRevocationTest {
    private val notesRequest = buildJsonObject {
        put("modules", JsonArray(listOf(JsonPrimitive("notes"))))
    }

    private fun peer(own: Boolean = true, notes: Boolean = true) = TelefonPeer(
        device_id = "11111111-1111-4111-8111-111111111111", display_name = "Desktop",
        static_public = "key", own_device = own, remote_own_device = true,
        personal_notes_sync_granted = notes, remote_personal_notes_sync_granted = true)

    @Test fun `eigene Geraetefreigabe wird unmittelbar vor dem Senden geprueft`() {
        assertTrue(personalSyncTransmissionAllowed(peer(), "personal_sync.request", notesRequest))
        assertFalse(personalSyncTransmissionAllowed(peer(own = false), "personal_sync.request", notesRequest))
    }

    @Test fun `lokale Bereichsfreigabe wird unmittelbar vor dem Senden geprueft`() {
        assertFalse(personalSyncTransmissionAllowed(peer(notes = false), "personal_sync.request", notesRequest))
    }

    @Test fun `Widerruf loescht nur Personal-Daten und Einstellungen bleiben sendbar`() {
        assertTrue(PERSONAL_SYNC_DATA_KINDS.toSet() == setOf(
            "personal_sync.request", "personal_sync.batch", "personal_sync.report",
            "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result",
            "personal_sync.deletion_proposals", "personal_sync.deletion_decision"))
        assertFalse("personal_sync.settings" in PERSONAL_SYNC_DATA_KINDS)
        assertTrue(personalSyncTransmissionAllowed(peer(own = false), "personal_sync.settings",
            buildJsonObject { put("own_device", JsonPrimitive(false)) }))
        val database = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonDatenbank.kt").readText()
        assertTrue(database.contains("writableInbox(peerId, message, result.first"))
        assertTrue(database.contains("storage.encryptPayload(TelefonKanonisch.bytes(message), \"inbox\""))
        assertFalse(database.contains("kind LIKE 'personal_sync.%'"))
    }
}
