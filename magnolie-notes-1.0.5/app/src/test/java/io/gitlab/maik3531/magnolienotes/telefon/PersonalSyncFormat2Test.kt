package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.AnhangPruefung
import java.util.Base64
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.security.MessageDigest

class PersonalSyncFormat2Test {
    private val run = "11111111-1111-4111-8111-111111111111"
    private val recordsHash = "a".repeat(64)
    private val hash = "b".repeat(64)

    @Test fun requestChunkAndResultAreExactAndCanonical() {
        val request = buildJsonObject {
            put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(run)); put("reply", JsonPrimitive(false))
            put("records_hash", JsonPrimitive(recordsHash)); put("wants", JsonArray(listOf(buildJsonObject {
                put("sha256", JsonPrimitive(hash)); put("ranges", JsonArray(listOf(JsonArray(listOf(JsonPrimitive(0), JsonPrimitive(1))))))
            })))
        }
        PersonalSyncProtokoll.validate("personal_sync.attachment_request", request)
        val raw = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
        val chunk = buildJsonObject {
            put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(run)); put("reply", JsonPrimitive(false))
            put("records_hash", JsonPrimitive(recordsHash)); put("sha256", JsonPrimitive(hash)); put("index", JsonPrimitive(0))
            put("data", JsonPrimitive(Base64.getEncoder().encodeToString(raw)))
        }
        PersonalSyncProtokoll.validate("personal_sync.attachment_chunk", chunk)
        assertThrows(TelefonProtokollFehler::class.java) { PersonalSyncProtokoll.validate(
            "personal_sync.attachment_chunk", buildJsonObject { chunk.forEach(::put); put("data", JsonPrimitive("iVBORw0KGgo")) }) }
        val result = buildJsonObject {
            put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(run)); put("reply", JsonPrimitive(false))
            put("records_hash", JsonPrimitive(recordsHash)); put("sha256", JsonPrimitive(hash))
            put("state", JsonPrimitive("complete")); put("error", JsonPrimitive("none"))
        }
        PersonalSyncProtokoll.validate("personal_sync.attachment_result", result)
        assertEquals(2, negotiatedPersonalNotesFormat(TelefonPeer(run, "Desktop", "key",
            remote_personal_notes_sync_versions = listOf(1, 2))))
        assertEquals(1, negotiatedPersonalNotesFormat(TelefonPeer(run, "Desktop", "key")))
    }

    @Test fun `shared whitespace attachment identifier is rejected`() {
        val contract = TelefonKanonisch.json.parseToJsonElement(
            javaClass.getResource("/personal-sync-contract.json")!!.readText()).jsonObject
        val descriptor = contract.getValue("format2").jsonObject.getValue("descriptor").jsonObject
        val whitespace = contract.getValue("invalid").jsonObject.getValue("whitespace_attachment_id")
        val invalid = JsonObject(descriptor + ("attachment_id" to whitespace))
        assertThrows(TelefonProtokollFehler::class.java) {
            val value = buildJsonObject {
                put("title", JsonPrimitive("")); put("text", JsonPrimitive("")); put("html", JsonPrimitive(""))
                put("notebook_id", JsonPrimitive("book")); put("symbol", JsonPrimitive("note"))
                put("created_ms", JsonPrimitive(1)); put("modified_ms", JsonPrimitive(1))
                put("attachments", JsonArray(listOf(invalid)))
            }
            val record = buildJsonObject {
                put("kind", JsonPrimitive("note")); put("id", JsonPrimitive("note")); put("state", JsonPrimitive("live"))
                put("clock", JsonArray(listOf(buildJsonObject { put("actor_id", JsonPrimitive(run)); put("counter", JsonPrimitive(1)) })))
                put("hash", JsonPrimitive(io.gitlab.maik3531.magnolienotes.daten.PersonalSync.hash(value)))
                put("modified_ms", JsonPrimitive(1)); put("value", value)
            }
            PersonalSyncProtokoll.validate("personal_sync.batch", buildJsonObject {
                put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(run)); put("batch_id", JsonPrimitive(run))
                put("sequence", JsonPrimitive(0)); put("last", JsonPrimitive(true)); put("reply", JsonPrimitive(false))
                put("records_hash", JsonPrimitive(recordsHash)); put("records", JsonArray(listOf(record)))
            })
        }
    }

    @Test fun `identifier boundaries reject edges and preserve valid interior spaces`() {
        val contract = TelefonKanonisch.json.parseToJsonElement(
            javaClass.getResource("/personal-sync-contract.json")!!.readText()).jsonObject
        val invalid = contract.getValue("invalid").jsonObject
        val descriptor = contract.getValue("format2").jsonObject.getValue("descriptor").jsonObject
        fun validate(id: String) {
            val value = buildJsonObject {
                put("title", JsonPrimitive("")); put("text", JsonPrimitive("")); put("html", JsonPrimitive(""))
                put("notebook_id", JsonPrimitive("book part")); put("symbol", JsonPrimitive("note"))
                put("created_ms", JsonPrimitive(1)); put("modified_ms", JsonPrimitive(1))
                put("attachments", JsonArray(listOf(JsonObject(descriptor + ("attachment_id" to JsonPrimitive(id))))))
            }
            val record = buildJsonObject {
                put("kind", JsonPrimitive("note")); put("id", JsonPrimitive("note part")); put("state", JsonPrimitive("live"))
                put("clock", JsonArray(listOf(buildJsonObject { put("actor_id", JsonPrimitive(run)); put("counter", JsonPrimitive(1)) })))
                put("hash", JsonPrimitive(io.gitlab.maik3531.magnolienotes.daten.PersonalSync.hash(value)))
                put("modified_ms", JsonPrimitive(1)); put("value", value)
            }
            PersonalSyncProtokoll.validate("personal_sync.batch", buildJsonObject {
                put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(run)); put("batch_id", JsonPrimitive(run))
                put("sequence", JsonPrimitive(0)); put("last", JsonPrimitive(true)); put("reply", JsonPrimitive(false))
                put("records_hash", JsonPrimitive(recordsHash)); put("records", JsonArray(listOf(record)))
            })
        }
        for (name in listOf("leading_space_id", "trailing_space_id", "leading_tab_id", "trailing_tab_id"))
            assertThrows(TelefonProtokollFehler::class.java) { validate(invalid.getValue(name).jsonPrimitive.content) }
        validate(invalid.getValue("interior_space_id").jsonPrimitive.content)
    }

    @Test fun `deletion entity and parent identifiers have canonical boundaries`() {
        fun body(id: String, parent: String) = buildJsonObject {
            put("format", JsonPrimitive(1)); put("run_id", JsonPrimitive(run)); put("proposal_batch_id", JsonPrimitive(run))
            put("sequence", JsonPrimitive(0)); put("last", JsonPrimitive(true)); put("proposals", JsonArray(listOf(buildJsonObject {
                put("proposal_id", JsonPrimitive("22222222-2222-4222-8222-222222222222")); put("kind", JsonPrimitive("attachment"))
                put("id", JsonPrimitive(id)); put("parent_id", JsonPrimitive(parent)); put("clock", JsonArray(listOf(buildJsonObject {
                    put("actor_id", JsonPrimitive(run)); put("counter", JsonPrimitive(1))
                }))); put("prior_hash", JsonPrimitive(hash)); put("deleted_ms", JsonPrimitive(1)); put("label", JsonPrimitive("x"))
            })))
        }
        for (value in listOf(" id", "id ", "\tid", "id\t")) {
            assertThrows(TelefonProtokollFehler::class.java) { PersonalSyncProtokoll.decodeDeletionProposals(body(value, "parent")) }
            assertThrows(TelefonProtokollFehler::class.java) { PersonalSyncProtokoll.decodeDeletionProposals(body("id", value)) }
        }
        val decoded = PersonalSyncProtokoll.decodeDeletionProposals(body("id part", "parent part")).single()
        assertEquals("id part", decoded.id); assertEquals("parent part", decoded.parentId)
    }

    @Test fun desktopToAndroidFormat2VectorAndReleaseScenariosAreConsumed() {
        val contract = TelefonKanonisch.json.parseToJsonElement(
            javaClass.getResource("/personal-sync-contract.json")!!.readText()).jsonObject
        val cross = contract.getValue("format2_cross_platform").jsonObject
        val vector = cross.getValue("desktop_to_android").jsonObject
        val bytes = Base64.getDecoder().decode(vector.getValue("data_base64").jsonPrimitive.content)
        assertEquals(vector.getValue("size").jsonPrimitive.content.toInt(), bytes.size)
        assertEquals(vector.getValue("sha256").jsonPrimitive.content,
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) })
        assertEquals(vector.getValue("mime").jsonPrimitive.content, AnhangPruefung.mime(bytes))
        val scenarios = (cross.getValue("scenarios") as JsonArray).map { it.jsonPrimitive.content }.toSet()
        assertEquals(setOf("interrupted_chunks_resume_missing", "hash_magic_failure_domain_unchanged",
            "format1_fallback", "empty_attachment_list", "duplicate_hash_reuse", "additive_omitted",
            "concurrent_ownership", "save_failure_retry", "revoke", "auto_wifi_policy"), scenarios)
    }
}
