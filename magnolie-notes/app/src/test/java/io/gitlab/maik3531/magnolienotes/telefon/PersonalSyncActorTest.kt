package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PersonalSyncActorTest {
    @Test fun privateStorageIdentityCannotBeMistakenForAPairedPeer() {
        val run = "11111111-1111-4111-8111-111111111111"
        val storage = PersonalSyncActor.storagePeer(run)
        assertTrue(PersonalSyncActor.isStoragePeer(storage))
        assertFalse(PersonalSyncActor.isStoragePeer(run))
        assertFalse(storage.contains(':'))
        assertTrue(runCatching { TelefonNachrichten.uuid4(storage) }.isFailure)
        assertTrue(runCatching { PersonalSyncActor.storagePeer("unknown") }.isFailure)
    }

    @Test fun sameActorAckVectorsReuseTheExistingTransportAckRules() {
        val text = requireNotNull(javaClass.getResource("/notes-actor-ack.json")).readText()
        for (item in Json.parseToJsonElement(text).jsonObject.getValue("cases").jsonArray.map { it.jsonObject }) {
            val body = item.getValue("body").jsonObject
            val accepted = runCatching { PersonalSyncActor.validateAck(body) }.isSuccess
            assertEquals(item.string("name"), item.getValue("valid").jsonPrimitive.boolean, accepted)
            if (accepted) {
                assertEquals(body, PersonalSyncActor.ack(body.string("run_id"), body.string("message_id"), body.string("status"), body.string("error")))
                assertTrue(PersonalSyncActor.isReservedMessage(buildJsonObject { put("type", "message"); put("kind", PersonalSyncActor.ACK_KIND); put("body", body) }))
                assertTrue(runCatching { PersonalSyncActor.wrap(body.string("run_id"), PersonalSyncActor.ACK_KIND, body) }.isFailure)
            }
        }
    }

    @Test fun actorOverheadUsesFullPacketBudgetWithoutRelaxingTheInnerBatchLimit() {
        val fixture = Json.parseToJsonElement(requireNotNull(javaClass.getResource("/notes-actor-data.json")).readText()).jsonObject.getValue("wire_budget").jsonObject
        val run = "11111111-1111-4111-8111-111111111111"
        fun record(id: String, length: Int): JsonObject {
            val value = JsonObject(fixture.getValue("value").jsonObject + ("text" to JsonPrimitive("A".repeat(length))))
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest(TelefonKanonisch.bytes(value)).joinToString("") { "%02x".format(it) }
            return buildJsonObject {
                put("kind", "note"); put("id", id); put("state", "live"); put("modified_ms", 0)
                put("clock", JsonArray(listOf(buildJsonObject { put("actor_id", run); put("counter", 1) })))
                put("hash", hash); put("value", value)
            }
        }
        fun message(secondLength: Int): JsonObject = TelefonNachrichten.message("personal_sync.batch", buildJsonObject {
            put("format", 1); put("run_id", run); put("batch_id", "33333333-3333-4333-8333-333333333333")
            put("sequence", 0); put("last", true); put("reply", false)
            put("records", JsonArray(listOf(record("note-a", 128 * 1024), record("note-b", secondLength))))
        }, 60000, 1700000000000L, "22222222-2222-4222-8222-222222222222")
        val target = fixture.getValue("portable_body_bytes").jsonPrimitive.int
        val original = message(target - TelefonKanonisch.bytes(message(0).getValue("body")).size)
        assertEquals(target, TelefonKanonisch.bytes(original.getValue("body")).size)
        TelefonNachrichten.validate(original, 1700000000000L)
        val envelope = PersonalSyncActor.wrap(run, "personal_sync.batch", original.getValue("body").jsonObject)
        assertTrue(TelefonKanonisch.bytes(envelope).size <= 256 * 1024)
        val wrapped = JsonObject(original + mapOf("kind" to JsonPrimitive(PersonalSyncActor.DATA_KIND), "body" to envelope))
        assertTrue(TelefonKanonisch.bytes(wrapped).size > 192 * 1024 && TelefonKanonisch.bytes(wrapped).size <= 256 * 1024)
        assertEquals(wrapped, PersonalSyncActor.wireMessage(original, run))
    }

    @Test fun sameCrossPlatformDataVectorsAndOriginalBodyRoundtrip() {
        val text = requireNotNull(javaClass.getResource("/notes-actor-data.json")).readText()
        val cases = Json.parseToJsonElement(text).jsonObject.getValue("cases").jsonArray
        for (item in cases.map { it.jsonObject }) {
            val body = item.getValue("body").jsonObject
            val accepted = runCatching { PersonalSyncActor.validateData(body) }.isSuccess
            assertEquals(item.string("name"), item.getValue("valid").jsonPrimitive.boolean, accepted)
            if (accepted) {
                assertEquals(body, PersonalSyncActor.wrap(body.string("run_id"), body.string("kind"), body.getValue("body").jsonObject))
                assertEquals(body.string("kind") to body.getValue("body").jsonObject, PersonalSyncActor.unwrap(body))
            }
        }
    }

    @Test fun sameCrossPlatformStartVectors() {
        val text = requireNotNull(javaClass.getResource("/notes-actor-start.json")).readText()
        val cases = Json.parseToJsonElement(text).jsonObject.getValue("cases").jsonArray
        for (item in cases.map { it.jsonObject }) {
            val body = item.getValue("body").jsonObject
            val accepted = runCatching { PersonalSyncActor.validateStart(body) }.isSuccess
            assertEquals(item.string("name"), item.getValue("valid").jsonPrimitive.boolean, accepted)
            if (accepted) assertEquals(body, PersonalSyncActor.start(body.string("run_id")))
        }
    }

    @Test fun bothModulesAndPeersMustSupportTheSharedAndActorContract() {
        val local = listOf("personal_notes_sync", "personal_tasks_sync").associateWith {
            TelefonCapability(true, "available", listOf(9, 12))
        }
        val peer = TelefonPeer("22222222-2222-4222-8222-222222222222", "Synthetic", "key",
            remote_personal_notes_sync_available = true, remote_personal_tasks_sync_available = true,
            remote_personal_notes_sync_versions = listOf(9, 12), remote_personal_tasks_sync_versions = listOf(9, 12))
        assertTrue(PersonalSyncActor.supported(peer, local))
        assertFalse(PersonalSyncActor.supported(peer.copy(remote_personal_notes_sync_versions = listOf(9)), local))
        assertFalse(PersonalSyncActor.supported(peer.copy(remote_personal_tasks_sync_versions = listOf(12)), local))
        assertFalse(PersonalSyncActor.supported(peer.copy(remote_personal_tasks_sync_available = false), local))
        assertFalse(PersonalSyncActor.supported(peer, local + ("personal_notes_sync" to TelefonCapability(true, "available", listOf(9)))))
    }
}
