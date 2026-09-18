package io.gitlab.maik3531.magnolienotes.telefon

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class PersonalCustomConsentTest {
    private val vectors = Json.parseToJsonElement(File("../contracts/personal-custom-consent-v4-vectors.json").readText()).jsonObject
    private val source = vectors["source_id"]!!.jsonPrimitive.content
    private val local = vectors["local"]!!.jsonObject
    private val remote = vectors["remote"]!!.jsonObject
    private val versions = listOf(1, 2, 3, 4)

    @Test fun identityVectorsAndLongIds() {
        for (raw in vectors["identities"] as JsonArray) {
            val item = raw.jsonObject["item_id"]!!.jsonPrimitive.content
            val expected = raw.jsonObject["id"]!!.jsonPrimitive.content
            assertEquals(expected, PersonalSyncProtokoll.customSourceId(source, item))
            assertNotEquals(expected, PersonalSyncProtokoll.customSourceId(vectors["other_source_id"]!!.jsonPrimitive.content, item))
        }
        assertEquals(vectors["long_identity"]!!.jsonObject["id"]!!.jsonPrimitive.content,
            PersonalSyncProtokoll.customSourceId(source, "a".repeat(640)))
        assertEquals(vectors["unicode_identity"]!!.jsonObject["id"]!!.jsonPrimitive.content,
            PersonalSyncProtokoll.customSourceId(source, "\uD83C\uDF31".repeat(160)))
        for (id in listOf("", "a".repeat(641), "\ud800", "a\u0000b", "a\nb", "a\u007fb", "\uD83C\uDF31".repeat(161))) {
            assertThrows(TelefonProtokollFehler::class.java) { PersonalSyncProtokoll.customSourceId(source, id) }
        }
    }

    @Test fun exactSettingsAndBilateralFences() {
        for (invalid in vectors["invalid_settings"] as JsonArray) {
            assertThrows(TelefonProtokollFehler::class.java) { PersonalSyncProtokoll.validateCustomSettings(invalid.jsonObject) }
        }
        fun allowed(l: JsonObject? = local, r: JsonObject? = remote,
            lv: List<Int> = versions, rv: List<Int> = versions, own: Boolean = true, other: Boolean = true) =
            PersonalSyncProtokoll.customScopeAllowed(l, r, lv, rv, own, other,
                remote["epoch"]!!.jsonPrimitive.content, local["epoch"]!!.jsonPrimitive.content, 1, 1)
        assertTrue(allowed())
        assertFalse(allowed(l = null)); assertFalse(allowed(r = null))
        assertFalse(allowed(lv = listOf(1, 2, 3))); assertFalse(allowed(rv = listOf(1, 2, 3)))
        assertFalse(allowed(own = false)); assertFalse(allowed(other = false))
        assertFalse(allowed(r = vectors["revoked"]!!.jsonObject))
        assertFalse(allowed(r = vectors["reenabled"]!!.jsonObject))
        assertFalse(allowed(r = JsonObject(remote + ("revision" to JsonPrimitive(3)))))
        assertThrows(TelefonProtokollFehler::class.java) { PersonalSyncProtokoll.validate("personal_sync.settings", local) }
        assertThrows(TelefonProtokollFehler::class.java) { PersonalSyncProtokoll.validate("personal_sync.custom_settings", local) }
    }

    @Test fun rollbackEquivocationAndSerialization() {
        var current: JsonObject? = null
        for (key in listOf("remote", "remote", "revoked", "reenabled")) {
            current = Json.parseToJsonElement(PersonalSyncProtokoll.acceptCustomSettings(current, vectors[key]!!.jsonObject).toString()).jsonObject
        }
        for (key in listOf("remote", "revoked")) {
            assertThrows(TelefonProtokollFehler::class.java) { PersonalSyncProtokoll.acceptCustomSettings(current, vectors[key]!!.jsonObject) }
        }
        for (change in listOf("enabled" to JsonPrimitive(false), "revision" to JsonPrimitive(4))) {
            assertThrows(TelefonProtokollFehler::class.java) {
                PersonalSyncProtokoll.acceptCustomSettings(current, JsonObject(current!! + change))
            }
        }
    }
}
