package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncState
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncClock
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncEntity
import io.gitlab.maik3531.magnolienotes.daten.PendingPersonalDecision

class PersonalNoteModeTest {
    @Test fun serializedComputerSelectionKeepsIndependentPoliciesAndKeyBindings() {
        val home = TelefonPeer("11111111-1111-4111-8111-111111111111", "Home", TelefonKrypto.b64(ByteArray(32) { 1 }),
            personal_note_policy = PersonalNoteMode.create(PersonalNoteMode.IMPORT), remote_personal_note_policy = PersonalNoteMode.create())
        val office = TelefonPeer("22222222-2222-4222-8222-222222222222", "Office", TelefonKrypto.b64(ByteArray(32) { 2 }),
            personal_note_policy = PersonalNoteMode.create(), remote_personal_note_policy = PersonalNoteMode.create())
        val codec = Json { encodeDefaults = true }
        fun reload(value: TelefonBestand): TelefonBestand {
            val normalized = sanitizeLegacyPeer(codec.encodeToJsonElement(TelefonBestand.serializer(), value).jsonObject).first
            return codec.decodeFromJsonElement(TelefonBestand.serializer(), normalized).validated()
        }
        var saved = reload(TelefonBestand().remember(home).remember(office))
        saved = reload(saved.select(home.device_id))
        assertTrue(PersonalNoteMode.importing(saved.peer!!.personal_note_policy, saved.peer!!.remote_personal_note_policy))
        assertEquals(office, saved.other_peers.single())
        saved = reload(saved.remember(saved.peer!!.copy(personal_note_policy = PersonalNoteMode.create(PersonalNoteMode.TWO_WAY, 2))))
        saved = reload(saved.select(office.device_id))
        assertEquals(office.personal_note_policy, saved.peer!!.personal_note_policy)
        assertEquals(office.remote_personal_note_policy, saved.peer!!.remote_personal_note_policy)
        assertEquals(2L, saved.other_peers.single().personal_note_policy!!.long("revision"))
        assertThrows(IllegalArgumentException::class.java) { saved.remember(home.copy(static_public = office.static_public)) }
    }
    @Test fun aNewConnectionRequiresControlsAndCurrentPolicySnapshots() {
        val local = PersonalNoteMode.create()
        val remote = PersonalNoteMode.create(PersonalNoteMode.IMPORT)
        val sent = PersonalNoteMode.echo(local, remote)
        val received = PersonalNoteMode.echo(remote, local)
        val session = PersonalNoteSession().also { it.sent = sent; it.received = received }
        assertFalse(session.ready(sent, received))
        session.capabilitiesReceived = true; session.grantsReceived = true
        assertFalse(session.ready(sent, received))
        session.ownSettingsReceived = true
        assertTrue(session.ready(sent, received))
        assertFalse(session.ready(PersonalNoteMode.create(PersonalNoteMode.IMPORT, 2), received))
        assertFalse(PersonalNoteSession().ready(sent, received))
    }
    @Test fun deletionKindProofIsBoundToPeerDirectionAndExactClock() {
        val actor = "11111111-1111-4111-8111-111111111111"
        val clock = listOf(PersonalSyncClock(actor, 2))
        val state = PersonalSyncState(
            entities = mapOf("task\u0000task" to PersonalSyncEntity(clock = clock, peer_device_id = "desktop", proposal_id = "outgoing")),
            pending_decisions = listOf(PendingPersonalDecision("desktop", "run", "decision", "incoming", "delete", clock, kind = "task")))
        fun body(id: String, counter: Long = 2) = buildJsonObject {
            put("decisions", JsonArray(listOf(buildJsonObject {
                put("proposal_id", JsonPrimitive(id))
                put("expected_clock", JsonArray(listOf(buildJsonObject {
                    put("actor_id", JsonPrimitive(actor)); put("counter", JsonPrimitive(counter))
                })))
            })))
        }
        assertEquals(listOf("task"), PersonalNoteMode.decisionKinds(state, "desktop", body("outgoing"), false))
        assertEquals(listOf("task"), PersonalNoteMode.decisionKinds(state, "desktop", body("incoming"), true))
        assertNull(PersonalNoteMode.decisionKinds(state, "other", body("incoming"), true))
        assertNull(PersonalNoteMode.decisionKinds(state, "desktop", body("incoming", 3), true))
        assertNull(PersonalNoteMode.decisionKinds(state, "desktop", body("outgoing"), true))
        assertNull(PersonalNoteMode.decisionKinds(state, "desktop", body("incoming"), false))
    }
    private fun with(base: JsonObject, vararg values: Pair<String, JsonElement>) = JsonObject(base + values)
    private fun record(kind: String) = buildJsonObject { put("kind", JsonPrimitive(kind)) }
    private fun list(field: String, vararg kinds: String) = buildJsonObject { put(field, JsonArray(kinds.map(::record))) }

    @Test fun policyRequiresAnExactTypedSchemaAndFreshRevisions() {
        assertEquals(JsonPrimitive(PersonalNoteMode.IMPORT), PersonalNoteMode.create()["mode"])
        val first = PersonalNoteMode.create(PersonalNoteMode.TWO_WAY)
        assertEquals(first, PersonalNoteMode.accept(null, first))
        assertEquals(first, PersonalNoteMode.accept(first, first))
        for (bad in listOf(
            with(first, "unknown" to JsonPrimitive(true)),
            with(first, "format" to JsonPrimitive(4)),
            with(first, "mode" to JsonPrimitive("mirror")),
            with(first, "revision" to JsonPrimitive("1")),
            with(first, "revision" to JsonPrimitive(0)),
            with(first, "revision" to JsonPrimitive(9_007_199_254_740_992L)),
            with(first, "epoch" to JsonPrimitive("not-a-uuid")),
            with(first, "peer_epoch" to JsonPrimitive("wrong"))))
            assertThrows(TelefonProtokollFehler::class.java) { PersonalNoteMode.validate(bad) }
        val next = PersonalNoteMode.create(PersonalNoteMode.IMPORT, 2)
        assertEquals(next, PersonalNoteMode.accept(first, next))
        assertThrows(TelefonProtokollFehler::class.java) { PersonalNoteMode.accept(next, first) }
        assertThrows(TelefonProtokollFehler::class.java) {
            PersonalNoteMode.accept(first, with(first, "mode" to JsonPrimitive(PersonalNoteMode.IMPORT)))
        }
        assertThrows(TelefonProtokollFehler::class.java) {
            PersonalNoteMode.accept(first, with(first, "revision" to JsonPrimitive(2)))
        }
    }

    @Test fun bothPoliciesNeedFreshConnectionEchoesAndEitherSideCanRequestImport() {
        val phone = PersonalNoteMode.create(PersonalNoteMode.IMPORT)
        val desktop = PersonalNoteMode.create(PersonalNoteMode.TWO_WAY)
        assertTrue(PersonalNoteMode.importing(phone, desktop))
        assertTrue(PersonalNoteMode.importing(desktop, phone))
        assertFalse(PersonalNoteMode.importing(desktop, desktop))
        assertFalse(PersonalNoteMode.ready(phone, desktop, true, true))
        val p = PersonalNoteMode.echo(phone, desktop); val d = PersonalNoteMode.echo(desktop, phone)
        assertEquals(p, PersonalNoteMode.accept(phone, p))
        assertTrue(PersonalNoteMode.ready(p, d, true, true))
        assertFalse(PersonalNoteMode.ready(p, d, false, true))
        assertFalse(PersonalNoteMode.ready(p, d, true, false))
        assertFalse(PersonalNoteMode.ready(PersonalNoteMode.create(PersonalNoteMode.IMPORT, 2), d, true, true))
    }

    @Test fun noteAndNotebookRecordsNeverTravelBackInImportMode() {
        for (role in listOf("phone", "desktop")) for (outgoing in listOf(true, false)) {
            val forward = if (outgoing) role == "phone" else role == "desktop"
            for (kind in listOf("note", "notebook")) {
                assertEquals(forward, PersonalNoteMode.allowed(role, outgoing, "personal_sync.batch", list("records", kind), true))
                assertEquals(forward, PersonalNoteMode.allowed(role, outgoing, "personal_sync.batch", list("records", "task", kind), true))
                assertTrue(PersonalNoteMode.allowed(role, outgoing, "personal_sync.batch", list("records", kind), false))
            }
            assertTrue(PersonalNoteMode.allowed(role, outgoing, "personal_sync.batch", list("records", "task"), true))
            assertTrue(PersonalNoteMode.allowed(role, outgoing, "personal_sync.batch", list("records"), true))
        }
    }

    @Test fun attachmentRequestsAndPayloadsHaveOppositeDirections() {
        val body = JsonObject(emptyMap())
        for (role in listOf("phone", "desktop")) for (outgoing in listOf(true, false)) {
            val forward = if (outgoing) role == "phone" else role == "desktop"
            assertEquals(forward, PersonalNoteMode.allowed(role, outgoing, "personal_sync.attachment_chunk", body, true))
            assertEquals(!forward, PersonalNoteMode.allowed(role, outgoing, "personal_sync.attachment_request", body, true))
            assertTrue(PersonalNoteMode.allowed(role, outgoing, "personal_sync.attachment_result", body, true))
            assertTrue(PersonalNoteMode.allowed(role, outgoing, "personal_sync.report", body, true))
            assertTrue(PersonalNoteMode.allowed(role, outgoing, "personal_sync.request", body, true))
        }
    }

    @Test fun importedCopiesRejectNoteDeletionsWhileTaskDecisionsRequireKnownProposals() {
        for (role in listOf("phone", "desktop")) for (outgoing in listOf(true, false)) {
            for (kind in listOf("note", "notebook", "attachment"))
                assertFalse(PersonalNoteMode.allowed(role, outgoing, "personal_sync.deletion_proposals", list("proposals", kind), true))
            assertTrue(PersonalNoteMode.allowed(role, outgoing, "personal_sync.deletion_proposals", list("proposals", "task"), true))
            val decisions = list("decisions", "ignored")
            assertFalse(PersonalNoteMode.allowed(role, outgoing, "personal_sync.deletion_decision", decisions, true))
            assertFalse(PersonalNoteMode.allowed(role, outgoing, "personal_sync.deletion_decision", decisions, true, listOf("note")))
            assertFalse(PersonalNoteMode.allowed(role, outgoing, "personal_sync.deletion_decision", decisions, true, emptyList()))
            assertTrue(PersonalNoteMode.allowed(role, outgoing, "personal_sync.deletion_decision", decisions, true, listOf("task")))
        }
    }
}
