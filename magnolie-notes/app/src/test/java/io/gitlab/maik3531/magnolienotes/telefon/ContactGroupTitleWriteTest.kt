package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ContactGroupTitleWriteTest {
    private val prepare = buildJsonObject {
        put("version", 20); put("request_id", "11111111-1111-4111-8111-111111111111")
        put("action", "prepare"); put("uid", "native-lookup"); put("old_title", "Work"); put("new_title", "Arbeit")
    }

    @Test fun separateEnvelopeDoesNotBroadenReadOrMembershipResources() {
        val message = TelefonNachrichten.message("device_status.request", prepare, 60_000)
        TelefonNachrichten.validate(message)
        val inspect = JsonObject(prepare + mapOf("action" to JsonPrimitive("inspect"), "group_id" to JsonPrimitive("42"),
            "account" to buildJsonObject { put("name", "fixture"); put("type", "provider"); put("data_set", "") }))
        TelefonNachrichten.validate(TelefonNachrichten.message("device_status.request", inspect, 60_000))
        assertThrows(Exception::class.java) { TelefonNachrichten.validate(TelefonNachrichten.message("device_status.request", JsonObject(inspect + ("token" to JsonPrimitive("11111111-1111-4111-8111-111111111111"))), 60_000)) }
        assertThrows(Exception::class.java) { ContactRead.validateRequest(prepare) }
        assertThrows(Exception::class.java) { ContactGroupWrite.validateRequest(prepare) }
        assertThrows(Exception::class.java) { ContactValueWrite.validateRequest(prepare) }
        for (invalid in listOf(JsonObject(prepare + ("account" to JsonObject(emptyMap()))),
            JsonObject(prepare + ("group_id" to JsonPrimitive("42"))), JsonObject(prepare + ("token" to JsonPrimitive("unexpected"))),
            JsonObject(prepare + ("new_title" to JsonPrimitive("Cafe\u0301"))), JsonObject(prepare + ("new_title" to JsonPrimitive("Work")))))
            assertThrows(Exception::class.java) { TelefonNachrichten.validate(TelefonNachrichten.message("device_status.request", invalid, 60_000)) }
        assertThrows(Exception::class.java) { TelefonNachrichten.validate(TelefonNachrichten.message("device_status.request", prepare, 60_001)) }
    }

    @Test fun generalConsentAndNegotiationRemainSeparateInTheWiredRuntime() {
        val peer = TelefonPeer("peer", "Synthetic", "key", own_device = true, remote_own_device = true,
            contacts_read_enabled = true, contacts_write_enabled = true,
            remote_device_status_available = true, remote_device_status_versions = listOf(5, 19, 20))
        assertTrue(ContactGroupTitleWrite.allowed(peer, true))
        assertFalse(ContactGroupTitleWrite.allowed(peer.copy(contacts_write_enabled = false), true))
        assertFalse(ContactGroupTitleWrite.allowed(peer.copy(contacts_read_enabled = false), true))
        assertFalse(ContactGroupTitleWrite.allowed(peer.copy(remote_device_status_versions = listOf(5, 19)), true))
        assertFalse(ContactGroupTitleWrite.allowed(peer, false))
        assertTrue(ContactGroupTitleWrite.RUNTIME_ENABLED)
        assertFalse(20 in TelefonCapabilities.phase1(contactRead = true, contactGroupsWrite = true, contactValuesWrite = true).getValue("device_status").versions)
        assertTrue(20 in TelefonCapabilities.phase1(contactRead = true, contactGroupTitlesWrite = true).getValue("device_status").versions)
    }

    @Test fun titlesUseUnicodeCodepointsAndRejectUnpairedSurrogates() {
        ContactGroupTitleWrite.validateRequest(JsonObject(prepare + ("new_title" to JsonPrimitive("😀".repeat(256)))))
        for (title in listOf("😀".repeat(257), "\uD800", " Ar", "Ar ", "Ar\nbeit", ""))
            assertThrows(Exception::class.java) { ContactGroupTitleWrite.validateRequest(JsonObject(prepare + ("new_title" to JsonPrimitive(title)))) }
    }
}
