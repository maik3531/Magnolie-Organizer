package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import io.gitlab.maik3531.magnolienotes.telefon.PersonalSyncProtokoll
import io.gitlab.maik3531.magnolienotes.telefon.TelefonProtokollFehler
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PersonalSyncTest {
    private val contract by lazy {
        Json.Default.parseToJsonElement(checkNotNull(javaClass.classLoader?.getResource(
            "personal-sync-contract.json")).readText()) as JsonObject
    }

    @Test fun sharedGoldenVector() {
        val value = contract["value"] as JsonObject
        assertEquals((contract["canonical"] as kotlinx.serialization.json.JsonPrimitive).content,
            PersonalSync.canonical(value).decodeToString())
        assertEquals((contract["sha256"] as kotlinx.serialization.json.JsonPrimitive).content, PersonalSync.hash(value))
        val unicode = contract["unicode_order"] as JsonObject
        assertEquals((unicode["canonical"] as JsonPrimitive).content,
            PersonalSync.canonical(unicode["value"]!!).decodeToString())
        val conflict = contract["conflict"] as JsonObject
        assertEquals((conflict["id_v4"] as kotlinx.serialization.json.JsonPrimitive).content,
            PersonalSync.conflictId("note", "note-1", (conflict["loser_hash"] as kotlinx.serialization.json.JsonPrimitive).content))
        val format2 = contract["format2"] as JsonObject
        val value2 = format2["value"] as JsonObject
        assertEquals((format2["canonical"] as JsonPrimitive).content, PersonalSync.canonical(value2).decodeToString())
        assertEquals((format2["sha256"] as JsonPrimitive).content, PersonalSync.hash(value2))
        val deletion = contract["deletions"] as JsonObject
        val deletionClock = (deletion["clock"] as JsonArray).map { value -> value as JsonObject
            PersonalSyncClock((value["actor_id"] as JsonPrimitive).content,
                (value["counter"] as JsonPrimitive).content.toLong()) }
        assertEquals((deletion["proposal_id"] as JsonPrimitive).content, PersonalSync.proposalId(
            (deletion["peer_device_id"] as JsonPrimitive).content, (deletion["kind"] as JsonPrimitive).content,
            (deletion["id"] as JsonPrimitive).content, (deletion["parent_id"] as JsonPrimitive).content,
            deletionClock, (deletion["prior_hash"] as JsonPrimitive).content))
        val snapshot = PersonalSync.attachmentDescriptor(Anhang("att-1", "image.png", "image",
            (format2["data_url"] as JsonPrimitive).content))!!
        assertEquals(format2["descriptor"], snapshot.descriptor)
    }

    @Test fun format2DescriptorProjectionIsExplicitAndFormat1Untouched() {
        val data = (contract["format2"] as JsonObject)["data_url"] as JsonPrimitive
        val note = Notiz("note", anhaenge = listOf(Anhang("att-1", "image.png", "image", data.content)))
        val (_, first) = PersonalSync.reconcile(Bestand(notizen = listOf(note)), setOf("notes"), 1)
        val (_, second) = PersonalSync.reconcile(Bestand(notizen = listOf(note)), setOf("notes"), 2)
        assertTrue("attachments" !in first.single { it.kind == "note" }.value)
        assertEquals(1, (second.single { it.kind == "note" }.value["attachments"] as JsonArray).size)
    }

    @Test fun sharedInvalidVectorsAndUtf8Boundaries() {
        val invalid = contract["invalid"] as JsonObject
        val value = contract["value"] as JsonObject
        val actor = "11111111-1111-4111-8111-111111111111"
        fun record(id: String = (invalid["id_160_utf8"] as JsonPrimitive).content,
                   clock: JsonArray = JsonArray(listOf(buildJsonObject {
                       put("actor_id", JsonPrimitive(actor)); put("counter", JsonPrimitive(1)) })),
                   projection: JsonObject = value,
                   modified: JsonPrimitive = projection["modified_ms"] as JsonPrimitive,
                   extra: Boolean = false): JsonObject = buildJsonObject {
            put("kind", JsonPrimitive("note")); put("id", JsonPrimitive(id)); put("state", JsonPrimitive("live"))
            put("clock", clock); put("hash", JsonPrimitive(PersonalSync.hash(projection)))
            put("modified_ms", modified); put("value", projection)
            if (extra) put((invalid["unexpected_field"] as JsonPrimitive).content, JsonPrimitive(1))
        }
        fun batch(record: JsonObject) = buildJsonObject {
            put("format", JsonPrimitive(1)); put("run_id", JsonPrimitive("11111111-1111-4111-8111-111111111111"))
            put("batch_id", JsonPrimitive("22222222-2222-4222-8222-222222222222")); put("sequence", JsonPrimitive(0))
            put("last", JsonPrimitive(true)); put("reply", JsonPrimitive(false)); put("records", JsonArray(listOf(record)))
        }
        assertEquals(160, (invalid["id_160_utf8"] as JsonPrimitive).content.toByteArray().size)
        PersonalSyncProtokoll.decodeBatch(batch(record()))
        val bad = listOf(record(id = (invalid["id_162_utf8"] as JsonPrimitive).content),
            record(modified = invalid["numeric_string"] as JsonPrimitive),
            record(modified = invalid["boolean_number"] as JsonPrimitive),
            record(modified = invalid["huge_timestamp"] as JsonPrimitive),
            record(clock = invalid["unsorted_clock"] as JsonArray),
            record(clock = invalid["duplicate_clock"] as JsonArray), record(extra = true),
            record(id = (invalid.getValue("whitespace_id") as JsonPrimitive).content),
            record(projection = JsonObject(value + ("created_ms" to invalid.getValue("numeric_string")))),
            record(projection = JsonObject(value + ("created_ms" to invalid.getValue("boolean_number")))))
        bad.forEach { candidate ->
            try { PersonalSyncProtokoll.decodeBatch(batch(candidate)); throw AssertionError("invalid vector accepted") }
            catch (_: TelefonProtokollFehler) { }
        }
        for (name in listOf("leading_space_id", "trailing_space_id", "leading_tab_id", "trailing_tab_id")) {
            val candidate = record(id = (invalid.getValue(name) as JsonPrimitive).content)
            try { PersonalSyncProtokoll.decodeBatch(batch(candidate)); throw AssertionError("boundary identifier accepted") }
            catch (_: TelefonProtokollFehler) { }
        }
        val interior = (invalid.getValue("interior_space_id") as JsonPrimitive).content
        assertEquals(interior, PersonalSyncProtokoll.decodeBatch(batch(record(id = interior))).single().id)
        val badNotebook = JsonObject(value + ("notebook_id" to invalid.getValue("leading_space_id")))
        try { PersonalSyncProtokoll.decodeBatch(batch(record(projection = badNotebook)))
            throw AssertionError("boundary notebook identifier accepted") }
        catch (_: TelefonProtokollFehler) { }
    }

    @Test fun additiveApplyPreservesAttachmentsAndForeignFields() {
        val actor = "11111111-1111-4111-8111-111111111111"
        val local = Notiz("note-1", titel = "Alt", anhaenge = listOf(Anhang("a", "x", "image", "data:image/png;base64,AA==")),
            baumQuelle = "eigene-lokale-metadaten")
        val value = contract["value"] as JsonObject
        val record = PersonalSyncRecord("note", "note-1", listOf(PersonalSyncClock(actor, 2)),
            PersonalSync.hash(value), 1700000000123, value)
        val input = Bestand(notizen = listOf(local), personalSync = PersonalSyncState(actor_id = actor, counter = 1,
            entities = mapOf("note\u0000note-1" to PersonalSyncEntity(listOf(PersonalSyncClock(actor, 1)), "0".repeat(64)))))
        val result = PersonalSync.apply(input, listOf(record)).bestand.notizen.single()
        assertEquals("Test", result.titel)
        assertEquals(1, result.anhaenge.size)
        assertEquals("eigene-lokale-metadaten", result.baumQuelle)
    }

    @Test fun foreignTasksAreExcludedAndAbsenceNeverDeletes() {
        val own = Aufgabe("own", titel = "Own")
        val foreign = Aufgabe("foreign", titel = "Foreign", fremdId = "x", herkunft = "branch")
        val (state, records) = PersonalSync.reconcile(Bestand(aufgaben = listOf(own, foreign)), setOf("tasks"))
        assertEquals(listOf("own"), records.map { it.id })
        assertEquals(2, PersonalSync.apply(state, emptyList()).bestand.aufgaben.size)
    }

    @Test fun concurrentSameHashOnlyMergesClock() {
        val first = "11111111-1111-4111-8111-111111111111"
        val second = "22222222-2222-4222-8222-222222222222"
        val value = contract["value"] as JsonObject
        val digest = PersonalSync.hash(value)
        val local = Notiz("note-1", titel = "Test", text = "Grüße", html = "", notizbuchId = "book-1",
            symbol = "notiz", angelegt = 1700000000000, geaendert = 1700000000123)
        val input = Bestand(notizen = listOf(local), personalSync = PersonalSyncState(entities = mapOf(
            "note\u0000note-1" to PersonalSyncEntity(listOf(PersonalSyncClock(first, 2)), digest, 1700000000123))))
        val result = PersonalSync.apply(input, listOf(PersonalSyncRecord("note", "note-1",
            listOf(PersonalSyncClock(second, 3)), digest, 1700000000123, value)))
        assertEquals(1, result.bestand.notizen.size)
        assertEquals(2, result.bestand.personalSync.entities.getValue("note\u0000note-1").clock.size)
        assertEquals(0, result.conflicts)
    }

    @Test fun concurrentRemoteWinnerMovesAttachmentsToLocalConflictOnly() {
        val first = "11111111-1111-4111-8111-111111111111"
        val second = "22222222-2222-4222-8222-222222222222"
        val attachment = Anhang("a", "x", "image", "data:image/png;base64,AA==")
        val local = Notiz("note-1", titel = "Local", anhaenge = listOf(attachment))
        val value = contract["value"] as JsonObject
        val remote = PersonalSyncRecord("note", "note-1", listOf(PersonalSyncClock(second, 1)),
            PersonalSync.hash(value), 1700000000123, value)
        val input = Bestand(notizen = listOf(local), personalSync = PersonalSyncState(entities = mapOf(
            "note\u0000note-1" to PersonalSyncEntity(listOf(PersonalSyncClock(first, 1)), "f".repeat(64), 1))))
        val notes = PersonalSync.apply(input, listOf(remote)).bestand.notizen
        assertEquals(2, notes.size)
        assertTrue(notes.single { it.id == "note-1" }.anhaenge.isEmpty())
        assertEquals(listOf(attachment), notes.single { it.id != "note-1" }.anhaenge)
        val repeated = PersonalSync.apply(PersonalSync.apply(input, listOf(remote)).bestand, listOf(remote))
        assertEquals(2, repeated.bestand.notizen.size)
        assertEquals(0, repeated.conflicts)
    }

    @Test fun concurrentLocalWinnerKeepsAttachmentsOnlyOnOriginal() {
        val first = "11111111-1111-4111-8111-111111111111"
        val second = "22222222-2222-4222-8222-222222222222"
        val attachment = Anhang("a", "x", "image", "data:image/png;base64,AA==")
        val local = Notiz("note-1", titel = "Local", anhaenge = listOf(attachment))
        val value = contract["value"] as JsonObject
        val remote = PersonalSyncRecord("note", "note-1", listOf(PersonalSyncClock(second, 1)),
            PersonalSync.hash(value), 1700000000123, value)
        val input = Bestand(notizen = listOf(local), personalSync = PersonalSyncState(entities = mapOf(
            "note\u0000note-1" to PersonalSyncEntity(listOf(PersonalSyncClock(first, 1)), "0".repeat(64), 1))))
        val notes = PersonalSync.apply(input, listOf(remote)).bestand.notizen
        assertEquals(listOf(attachment), notes.single { it.id == "note-1" }.anhaenge)
        assertTrue(notes.single { it.id != "note-1" }.anhaenge.isEmpty())
    }

    @Test fun foreignTreeNotesAreExcludedFailClosed() {
        val own = Notiz("own", titel = "Own")
        val foreign = Notiz("foreign", titel = "Foreign", baumQuelle = "other-branch")
        val (_, records) = PersonalSync.reconcile(Bestand(notizen = listOf(own, foreign)), setOf("notes"))
        assertTrue(records.any { it.kind == "note" && it.id == "own" })
        assertTrue(records.none { it.id == "foreign" })
    }

    @Test fun acknowledgedDeletionCreatesPeerBoundTombstoneAndSuppressesStaleLive() {
        val peer = "33333333-3333-4333-8333-333333333333"
        val note = Notiz("note-1", titel = "Delete me")
        val (baseline, _) = PersonalSync.reconcile(Bestand(notizen = listOf(note)), setOf("notes"), peerId = peer)
        val acknowledged = PersonalSync.acknowledge(baseline, peer)
        val (deleted, records) = PersonalSync.reconcile(acknowledged.copy(notizen = emptyList()), setOf("notes"), peerId = peer, nowMs = 10)
        val tombstone = deleted.personalSync.entities.getValue("note\u0000note-1")
        assertEquals("deleted", tombstone.state); assertEquals(peer, tombstone.peer_device_id)
        assertTrue(records.none { it.id == "note-1" })
        val stale = PersonalSync.reconcile(Bestand(notizen = listOf(note)), setOf("notes")).second.single { it.kind == "note" }
        assertTrue(PersonalSync.apply(deleted, listOf(stale)).bestand.notizen.isEmpty())
    }

    @Test fun unsyncedAbsenceDoesNotCreateTombstoneAndReplacementResetsBaseline() {
        val oldPeer = "33333333-3333-4333-8333-333333333333"
        val newPeer = "44444444-4444-4444-8444-444444444444"
        val note = Notiz("note-1", titel = "Delete me")
        val (baseline, _) = PersonalSync.reconcile(Bestand(notizen = listOf(note)), setOf("notes"), peerId = oldPeer)
        val (absent, _) = PersonalSync.reconcile(baseline.copy(notizen = emptyList()), setOf("notes"), peerId = oldPeer)
        assertEquals("live", absent.personalSync.entities.getValue("note\u0000note-1").state)
        val acknowledged = PersonalSync.acknowledge(baseline, oldPeer)
        val (replacement, _) = PersonalSync.reconcile(acknowledged, setOf("notes"), peerId = newPeer)
        assertTrue(!replacement.personalSync.entities.getValue("note\u0000note-1").acknowledged_by_peer)
    }

    @Test fun attachmentRemovalCreatesProposalButWholeNoteDoesNotDuplicateChild() {
        val peer = "33333333-3333-4333-8333-333333333333"
        val data = (contract["format2"] as JsonObject)["data_url"] as JsonPrimitive
        val note = Notiz("n", anhaenge = listOf(Anhang("a", "image.png", "image", data.content)))
        val (baseline, _) = PersonalSync.reconcile(Bestand(notizen = listOf(note)), setOf("notes"), 2, peer)
        val acknowledged = PersonalSync.acknowledge(baseline, peer)
        val (attachmentDeleted, _) = PersonalSync.reconcile(acknowledged.copy(
            notizen = listOf(note.copy(anhaenge = emptyList()))), setOf("notes"), 2, peer, 10)
        assertEquals("deleted", attachmentDeleted.personalSync.entities.getValue("attachment\u0000n\u0000a").state)
        assertEquals(1, PersonalSync.proposals(attachmentDeleted, peer).count { it.kind == "attachment" })
        val (noteDeleted, _) = PersonalSync.reconcile(acknowledged.copy(notizen = emptyList()),
            setOf("notes"), 2, peer, 10)
        assertEquals(1, PersonalSync.proposals(noteDeleted, peer).count { it.kind == "note" })
        assertTrue(PersonalSync.proposals(noteDeleted, peer).none { it.kind == "attachment" })
    }
}
