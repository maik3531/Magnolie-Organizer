package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.baum.KontaktDaten
import io.gitlab.maik3531.magnolienotes.baum.KontaktWert
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ContactValueWriteTest {
    private val prepare = buildJsonObject {
        put("version", ContactValueWrite.VERSION); put("request_id", "11111111-1111-4111-8111-111111111111")
        put("action", "prepare"); put("uid", "native-lookup"); put("field_names", JsonArray(listOf(JsonPrimitive("telefone"))))
    }
    private val contact = KontaktDaten(telefone = listOf(KontaktWert("mobil", "111")))
    private val token = "22222222-2222-4222-8222-222222222222"
    private val account = buildJsonObject { put("name", "fixture@example.invalid"); put("type", "provider"); put("data_set", "") }
    private fun apply(fields: JsonObject = ContactValueWrite.values(contact, setOf("telefone"))) = JsonObject(
        (prepare - "field_names") + mapOf("action" to JsonPrimitive("apply"), "token" to JsonPrimitive(token), "fields" to fields))

    @Test fun generalWriteConsentDoesNotComeFromReadPermissionOrAnOldGroupOptOut() {
        val peer = TelefonPeer("peer", "Synthetic", "key", own_device = true, remote_own_device = true,
            contacts_read_enabled = true, contact_groups_write_enabled = false,
            remote_device_status_available = true, remote_device_status_versions = listOf(5, 19))
        assertFalse(peer.contacts_write_enabled)
        assertTrue(ContactRead.allowed(peer, true)); assertFalse(ContactValueWrite.allowed(peer, true))
        val enabled = peer.copy(contacts_write_enabled = true)
        assertTrue(ContactValueWrite.allowed(enabled, true)); assertFalse(ContactValueWrite.allowed(enabled, false))
        assertFalse(ContactValueWrite.allowed(enabled.copy(remote_device_status_versions = listOf(5, 17)), true))
        assertFalse(ContactValueWrite.allowed(enabled.copy(contacts_read_enabled = false), true))
        assertTrue(ContactValueWrite.RUNTIME_ENABLED)
        val serialized = TelefonKanonisch.json.encodeToJsonElement(TelefonPeer.serializer(), peer).jsonObject
        val legacy = TelefonKanonisch.json.decodeFromJsonElement(TelefonPeer.serializer(), JsonObject(serialized - "contacts_write_enabled"))
        assertFalse(legacy.contacts_write_enabled)
    }

    @Test fun resourceIsSeparateStrictAndNotAdvertisedBeforeWiring() {
        ContactValueWrite.validateRequest(prepare); ContactValueWrite.validateRequest(apply())
        assertFalse(ContactValueWrite.VERSION in TelefonCapabilities.phase1(contactRead = true, contactGroupsWrite = true).getValue("device_status").versions)
        assertTrue(ContactValueWrite.VERSION in TelefonCapabilities.phase1(contactRead = true, contactValuesWrite = true).getValue("device_status").versions)
        for (invalid in listOf(JsonObject(prepare + ("version" to JsonPrimitive(5))),
            JsonObject(prepare + ("field_names" to JsonArray(emptyList()))),
            JsonObject(prepare + ("field_names" to JsonArray(listOf(JsonPrimitive("telefone"), JsonPrimitive("telefone"))))),
            JsonObject(prepare + ("field_names" to JsonArray(listOf(JsonPrimitive("foto"))))),
            JsonObject(prepare + ("fields" to JsonObject(emptyMap()))),
            JsonObject(apply() + ("token" to JsonPrimitive("invalid")))))
            assertThrows(Exception::class.java) { ContactValueWrite.validateRequest(invalid) }
        assertThrows(Exception::class.java) { ContactRead.validateRequest(prepare) }
        assertThrows(Exception::class.java) { ContactGroupWrite.validateRequest(prepare) }
    }

    @Test fun fieldValuesRejectMalformedRowsAndNormalizedDuplicateProjections() {
        fun phones(rows: List<KontaktWert>) = ContactValueWrite.values(KontaktDaten(telefone = rows), setOf("telefone"))
        val invalid = listOf(phones(listOf(KontaktWert("mobil", "111"), KontaktWert("privat", "+1 11"))),
            phones(listOf(KontaktWert("mobil", "\uD800"))), phones(listOf(KontaktWert("fax", "111"))),
            phones(listOf(KontaktWert("mobil", "line\nbreak"))), phones(List(101) { KontaktWert("mobil", it.toString()) }),
            buildJsonObject { put("telefone", buildJsonArray { add(buildJsonObject { put("art", "mobil"); put("wert", true) }) }) },
            buildJsonObject { put("foto", "unnegotiated") })
        invalid.forEach { assertThrows(Exception::class.java) { ContactValueWrite.validateRequest(apply(it)) } }
        ContactValueWrite.validateRequest(apply(phones(emptyList())))
        val emails = ContactValueWrite.values(KontaktDaten(emailEintraege = listOf(KontaktWert("privat", "a@example.invalid"),
            KontaktWert("arbeit", " A@example.invalid "))), setOf("emailEintraege"))
        assertThrows(Exception::class.java) { ContactValueWrite.validateRequest(apply(emails)) }
    }

    @Test fun onlyActualApplyReportsCanClaimSavedAndAccountIdentityIsExact() {
        val report = ContactValueWrite.report(prepare, token, contact, setOf("telefone"), account)
        ContactValueWrite.validateReport(report)
        assertEquals("prepared", report["state"]!!.jsonPrimitive.content)
        assertThrows(Exception::class.java) { ContactValueWrite.validateReport(JsonObject(report + ("state" to JsonPrimitive("saved")))) }
        assertThrows(Exception::class.java) { ContactValueWrite.validateReport(JsonObject(report - "account")) }
        assertThrows(Exception::class.java) { ContactValueWrite.validateReport(JsonObject(report + ("account" to JsonObject(account - "data_set")))) }
        assertEquals("saved", ContactValueWrite.report(apply(), token, contact, setOf("telefone"), account)["state"]!!.jsonPrimitive.content)
    }
}
