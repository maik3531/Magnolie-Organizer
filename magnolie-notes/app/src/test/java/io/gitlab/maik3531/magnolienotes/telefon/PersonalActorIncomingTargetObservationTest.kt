package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.*
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class PersonalActorIncomingTargetObservationTest {
    private val peer = "22222222-2222-4222-8222-222222222222"
    private val run = "44444444-4444-4444-8444-444444444444"
    private val actor = "11111111-1111-4111-8111-111111111111"
    private val clock = listOf(PersonalSyncClock(actor, 1))
    private inner class Fixture(val kind: String) {
        val parent = if (kind == "attachment") "own-note" else ""
        val id = when (kind) { "note" -> "own-note"; "task" -> "own-task"; else -> "own-file" }
        val key = kind + "\u0000" + (if (parent.isNotEmpty()) parent + "\u0000" else "") + id
        var book = Bestand(notizen = listOf(Notiz("own-note", text = "PRIVATE CONTENT",
            anhaenge = listOf(Anhang("own-file", "private.png", "image", "PRIVATE BLOB")))),
            aufgaben = listOf(Aufgabe("own-task", titel = "PRIVATE TASK")),
            personalSync = PersonalSyncState(peer_device_id = peer, entities = mapOf(key to PersonalSyncEntity(
                peer_device_id = peer, hash = "a".repeat(64), clock = clock, parent_id = parent))))
        var owner = true
        var source: String? = "b".repeat(64)
        var scope = PhoneContentScope.create(emptyList(), emptyList())
        var saved: JsonObject? = buildJsonObject { put("book_source", "c".repeat(64)); put("sequence", 1); put("sha256", "d".repeat(64)) }
        val target = buildJsonObject {
            put("proposal_id", UUID.randomUUID().toString()); put("kind", kind); put("id", id); put("parent_id", parent)
            put("prior_hash", "a".repeat(64)); put("clock", JsonArray(listOf(buildJsonObject { put("actor_id", actor); put("counter", 1) })))
        }
        fun create() = PersonalActorIncomingTargetObservation(peer, run, { owner }, { source }, { book }, { saved }, { scope })
    }

    @Test fun exactOwnLiveTargetsReturnMetadataOnlyAndAlwaysRequireConflictChoice() {
        for (kind in listOf("note", "task", "attachment")) {
            val f = Fixture(kind); val before = f.book; val beforeScope = f.scope; val beforeSaved = f.saved
            val result = f.create().observeMany(run, listOf(f.target)).single()
            assertEquals(f.target, result["target"])
            assertEquals(JsonPrimitive(true), result["metadata_matches"])
            assertEquals(JsonPrimitive(true), result["requires_conflict_choice"])
            assertFalse(result.toString().contains("PRIVATE"))
            assertSame(before, f.book); assertEquals(beforeScope, f.scope); assertEquals(beforeSaved, f.saved)
        }
    }

    @Test fun changedContentWithMatchingOldMetadataDoesNotBecomeConflictFree() {
        val f = Fixture("note")
        f.book = f.book.copy(notizen = f.book.notizen.map { it.copy(text = "Changed actual content") })
        val result = f.create().observeMany(run, listOf(f.target)).single()
        assertEquals(JsonPrimitive(true), result["metadata_matches"])
        assertEquals(JsonPrimitive(true), result["requires_conflict_choice"])
    }

    @Test fun oldAckOrMissingDuplicateAndUnownedLiveObjectsNeverBecomeObservations() {
        for (kind in listOf("note", "task", "attachment")) for (fault in listOf("old-ack", "missing", "duplicate", "unowned", "peer", "deleted", "conflict")) {
            val f = Fixture(kind); val meta = f.book.personalSync.entities.getValue(f.key)
            when (fault) {
                "old-ack" -> f.book = f.book.copy(personalSync = f.book.personalSync.copy(entities = mapOf(f.key to PersonalSyncEntity(acknowledged_by_peer = true))))
                "peer" -> f.book = f.book.copy(personalSync = f.book.personalSync.copy(peer_device_id = run))
                "deleted", "conflict" -> f.book = f.book.copy(personalSync = f.book.personalSync.copy(entities = mapOf(f.key to
                    meta.copy(state = if (fault == "deleted") "deleted" else "live", conflict = fault == "conflict"))))
                "missing" -> f.book = when (kind) { "task" -> f.book.copy(aufgaben = emptyList()); "note" -> f.book.copy(notizen = emptyList())
                    else -> f.book.copy(notizen = f.book.notizen.map { it.copy(anhaenge = emptyList()) }) }
                "duplicate" -> f.book = when (kind) { "task" -> f.book.copy(aufgaben = f.book.aufgaben + f.book.aufgaben)
                    "note" -> f.book.copy(notizen = f.book.notizen + f.book.notizen)
                    else -> f.book.copy(notizen = f.book.notizen.map { it.copy(anhaenge = it.anhaenge + it.anhaenge) }) }
                "unowned" -> f.book = if (kind == "task") f.book.copy(aufgaben = f.book.aufgaben.map { it.copy(delegiertAn = "foreign") })
                    else f.book.copy(notizen = f.book.notizen.map { it.copy(baumQuelle = "foreign") })
            }
            assertTrue("$kind/$fault", runCatching { f.create().observeMany(run, listOf(f.target)) }.isFailure)
        }
    }

    @Test fun everyLookupIsBoundToOwnerSourceScopeAndActualSavedBook() {
        for (fault in listOf("owner", "source", "scope", "book", "saved", "missing-save", "run")) {
            val f = Fixture("note"); val observer = f.create()
            observer.observeMany(run, listOf(f.target))
            when (fault) {
                "owner" -> f.owner = false
                "source" -> f.source = "e".repeat(64)
                "scope" -> f.scope = PhoneContentScope.create(listOf("different"), emptyList())
                "book" -> f.book = f.book.copy()
                "saved" -> f.saved = JsonObject(f.saved!! + ("sequence" to JsonPrimitive(2)))
                "missing-save" -> f.saved = null
            }
            assertTrue(fault, runCatching { observer.observeMany(if (fault == "run") peer else run, listOf(f.target)) }.isFailure)
        }
    }

    @Test fun currentContentMembersNeverAcquireIndependentTargetEvidence() {
        for (kind in listOf("note", "task", "attachment")) {
            val f = Fixture(kind)
            f.scope = PhoneContentScope.create(if (kind == "task") emptyList() else listOf("own-note"),
                if (kind == "task") listOf("own-task") else emptyList())
            assertTrue(runCatching { f.create().observeMany(run, listOf(f.target)) }.isFailure)
        }
    }

    @Test fun rejectedGroupRollsBackProvisionalProposalAndIdentityBindings() {
        val f = Fixture("note"); val observer = f.create()
        assertTrue(runCatching { observer.observeMany(run, listOf(f.target, f.target)) }.isFailure)
        val replacement = JsonObject(f.target + ("proposal_id" to JsonPrimitive(UUID.randomUUID().toString())))
        assertEquals(replacement, observer.observeMany(run, listOf(replacement)).single()["target"])
        assertTrue(runCatching { observer.observeMany(run, listOf(f.target)) }.isFailure)
    }

    @Test fun groupsAreBoundedAndStrictTargetShapesCannotCarryContent() {
        val f = Fixture("note"); val observer = f.create()
        for (targets in listOf(emptyList(), List(257) { f.target }, listOf(JsonObject(f.target + ("content" to JsonPrimitive("PRIVATE"))))))
            assertTrue(runCatching { observer.observeMany(run, targets) }.isFailure)
    }

    @Test fun malformedOrCallerShapedSavedClaimsAreRejected() {
        for (change in listOf("sequence" to JsonPrimitive("1"), "sequence" to JsonPrimitive(0),
            "book_source" to JsonPrimitive("invalid"), "sha256" to JsonPrimitive("invalid"), "caller" to JsonPrimitive(true))) {
            val f = Fixture("note"); f.saved = JsonObject(f.saved!! + change)
            assertTrue(runCatching { f.create() }.isFailure)
        }
    }
}
