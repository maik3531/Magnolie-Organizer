package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PersonalSyncActorTest {
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
