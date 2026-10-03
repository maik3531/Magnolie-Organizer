package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakt
import io.gitlab.maik3531.magnolienotes.baum.KontaktDaten
import io.gitlab.maik3531.magnolienotes.baum.KontaktWert
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class ContactReadTest {
    private fun request(action: String = "index", offset: Int = 0, uids: List<String> = emptyList()) = JsonObject(mapOf(
        "version" to JsonPrimitive(5), "request_id" to JsonPrimitive("11111111-1111-4111-8111-111111111111"),
        "action" to JsonPrimitive(action), "offset" to JsonPrimitive(offset), "uids" to JsonArray(uids.map(::JsonPrimitive))))

    @Test fun requiresIndependentPerComputerConsentAndBothOwnMarkers() {
        val peer = TelefonPeer("computer", "Computer", "key", own_device = true, remote_own_device = true,
            contacts_read_enabled = true, remote_device_status_available = true, remote_device_status_versions = listOf(1, 5))
        assertTrue(ContactRead.allowed(peer, true))
        assertFalse(ContactRead.allowed(peer, false))
        for (blocked in listOf(peer.copy(contacts_read_enabled = false), peer.copy(own_device = false),
            peer.copy(remote_own_device = false), peer.copy(remote_device_status_versions = listOf(1, 2, 3, 4)),
            peer.copy(remote_device_status_granted = false), peer.copy(device_status_granted = false), peer.copy(state = "paired_unverified")))
            assertFalse(ContactRead.allowed(blocked, true))
        assertFalse(ContactRead.allowed(peer.copy(device_id = "another", contacts_read_enabled = false), true))
        assertFalse(5 in TelefonCapabilities.phase1().getValue("device_status").versions)
        assertTrue(5 in TelefonCapabilities.phase1(contactRead = true).getValue("device_status").versions)
    }

    @Test fun boundedPagesAndSelectedCardsDoNotAllowWriteOperations() {
        assertEquals(emptyList<String>(), ContactRead.validateRequest(request()))
        assertEquals(listOf("lookup:1"), ContactRead.validateRequest(request("cards", uids = listOf("lookup:1"))))
        for (bad in listOf(request("delete"), request("cards"), request("cards", 1, listOf("x")),
            request("cards", uids = listOf("x", "x")), request(offset = 10001),
            request("cards", uids = listOf("x\nUID:other")), request("cards", uids = List(6) { "uid-$it" }),
            JsonObject(request() + ("write" to JsonPrimitive(true)))))
            assertTrue(runCatching { ContactRead.validateRequest(bad) }.isFailure)
        ContactRead.validateReport(ContactRead.report(request(), 0, emptyList()))
        assertTrue(runCatching { ContactRead.report(request(), 1, emptyList()) }.isFailure)
        val item = JsonObject(mapOf("uid" to JsonPrimitive("x"), "timestamp" to JsonPrimitive(1)))
        assertTrue(runCatching { ContactRead.report(request(), 2, listOf(item, item)) }.isFailure)
    }

    @Test fun exportsReadableMessengerRowsWithoutGuessingMembership() {
        assertNull(ContactReadAndroid.messenger("vnd.android.cursor.item/phone_v2", "+49123456789", "", ""))
        assertNull(ContactReadAndroid.messenger("vnd.android.cursor.item/vnd.com.whatsapp.profile", "+49123456789", "", ""))
        val social = ContactReadAndroid.messenger("vnd.android.cursor.item/vnd.com.whatsapp.profile", "49123456789@s.whatsapp.net", "", "")!!
        assertEquals("whatsapp", social.string("dienst"))
        assertEquals("+49123456789", social.string("wert"))
        val card = ContactReadAndroid.vcard(AndroidKontakt("lookup:1", 1,
            KontaktDaten(vorname = "Zoë", nachname = "Example", notiz = "Line one\nLine two; value",
                telefone = listOf(KontaktWert("home", "+49123456789"))), providerGeaendert = 1700000000000), "", listOf(social))
        assertTrue(card.startsWith("BEGIN:VCARD\r\nVERSION:3.0\r\n"))
        assertTrue(card.contains("NOTE:Line one\\nLine two\\; value"))
        assertTrue(card.replace("\r\n ", "").contains("X-MAGNOLIE-SOZIALES-MEDIUM:"))
        assertTrue(card.contains("REV:2023-11-14T22:13:20Z"))
        assertTrue(card.split("\r\n").all { it.toByteArray(Charsets.UTF_8).size <= 75 })
        val report = ContactRead.report(request("cards", uids = listOf("lookup:1")), 1, listOf(JsonObject(mapOf(
            "uid" to JsonPrimitive("lookup:1"), "timestamp" to JsonPrimitive(1700000000000), "vcard" to JsonPrimitive(card)))))
        ContactRead.validateReport(report)
    }
}
