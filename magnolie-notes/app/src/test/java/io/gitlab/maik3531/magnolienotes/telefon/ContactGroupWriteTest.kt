package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ContactGroupWriteTest {
    private val request = buildJsonObject {
        put("version", ContactGroupWrite.VERSION); put("request_id", "11111111-1111-4111-8111-111111111111")
        put("action", "prepare"); put("uid", "native-lookup")
    }
    private val token = "22222222-2222-4222-8222-222222222222"
    private fun apply(groups: List<String>) = JsonObject(request + mapOf(
        "action" to JsonPrimitive("apply"), "token" to JsonPrimitive(token), "groups" to JsonArray(groups.map(::JsonPrimitive))))

    @Test fun separateOptInAndBothGrantsAreRequiredEvenForAnOwnReadablePhone() {
        val read = TelefonPeer("peer", "Synthetic", "key", own_device = true, remote_own_device = true,
            contacts_read_enabled = true, remote_device_status_available = true, remote_device_status_versions = listOf(5, 16))
        assertTrue(ContactRead.allowed(read, true))
        assertFalse(ContactGroupWrite.allowed(read, true))
        val write = read.copy(contact_groups_write_enabled = true)
        assertTrue(ContactGroupWrite.allowed(write, true))
        for (peer in listOf(write.copy(own_device = false), write.copy(remote_own_device = false),
            write.copy(contacts_read_enabled = false), write.copy(device_status_granted = false),
            write.copy(remote_device_status_granted = false), write.copy(remote_device_status_versions = listOf(5))))
            assertFalse(ContactGroupWrite.allowed(peer, true))
        assertFalse(ContactGroupWrite.allowed(write, false))
        assertFalse(ContactGroupWrite.allowed(null, true))
    }

    @Test fun readOnlyCapabilitiesDoNotAdvertiseTheWriteResource() {
        fun versions(read: Boolean, write: Boolean) = TelefonCapabilities.phase1(contactRead = read, contactGroupsWrite = write).getValue("device_status").versions
        assertFalse(16 in versions(true, false))
        assertFalse(16 in versions(false, true))
        assertTrue(16 in versions(true, true))
    }

    @Test fun exactRequestsRejectExtraContactFieldsInvalidTokensAndAmbiguousGroupNames() {
        ContactGroupWrite.validateRequest(request); ContactGroupWrite.validateRequest(apply(emptyList()))
        ContactGroupWrite.validateRequest(apply(listOf("Work", "Team 👩‍💻")))
        for (invalid in listOf(JsonObject(request + ("name" to JsonPrimitive("Must not write names"))),
            JsonObject(apply(listOf("Work")) + ("token" to JsonPrimitive("invalid"))), apply(listOf("Work", " work ")),
            apply(listOf("line\nbreak")), apply(listOf("\uD800")), apply(List(101) { "Group $it" })))
            assertThrows(Exception::class.java) { ContactGroupWrite.validateRequest(invalid) }
        assertThrows(Exception::class.java) { ContactRead.validateRequest(request) }
    }

    @Test fun onlyActualApplyReportsMayClaimSaved() {
        val prepared = ContactGroupWrite.report(request, token, listOf("Coworkers"), listOf("Coworkers", "Work"))
        assertEquals("prepared", prepared["state"]!!.jsonPrimitive.content)
        assertThrows(IllegalArgumentException::class.java) { ContactGroupWrite.validateReport(JsonObject(prepared + ("state" to JsonPrimitive("saved")))) }
        val saved = ContactGroupWrite.report(apply(emptyList()), token, emptyList())
        assertEquals("saved", saved["state"]!!.jsonPrimitive.content)
        assertThrows(IllegalArgumentException::class.java) { ContactGroupWrite.validateReport(JsonObject(saved + ("catalog" to JsonArray(listOf(JsonPrimitive("Work")))))) }
    }
}
