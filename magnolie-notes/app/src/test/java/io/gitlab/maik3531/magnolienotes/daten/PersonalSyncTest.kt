package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.encodeToString
import kotlinx.serialization.decodeFromString
import io.gitlab.maik3531.magnolienotes.telefon.PersonalSyncProtokoll
import io.gitlab.maik3531.magnolienotes.telefon.TelefonProtokollFehler
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PersonalSyncTest {
    @Test fun `matching attached notes rekeys attachment parents and preserves deletion history`() {
        val actor = "11111111-1111-4111-8111-111111111111"
        val peer = "22222222-2222-4222-8222-222222222222"
        val file = Anhang("file", "image.png", "image", ((contract["format2"] as JsonObject)["data_url"] as JsonPrimitive).content)
        for (format in listOf(1, 2, 3)) for (variant in listOf("same", "different-id", "different-name", "deleted-history", "occupied-parent")) {
            val remoteFile = when (variant) { "different-id" -> file.copy(id = "other-file")
                "different-name" -> file.copy(name = "other.png"); else -> file }
            fun initial(id: String, device: String, attachment: Anhang) = PersonalSync.reconcile(
                Bestand(notizen = listOf(Notiz(id, titel = "Same", text = "Same", html = "Same", angelegt = 1, geaendert = 1,
                    anhaenge = listOf(attachment))), personalSync = PersonalSyncState(actor_id = device)), setOf("notes"), format, peer)
            val a = initial("z-local", actor, file); val b = initial("a-local", peer, remoteFile)
            var input = a.first
            val child = input.personalSync.entities["attachment\u0000z-local\u0000file"]
            if (format >= 2 && variant in listOf("deleted-history", "occupied-parent")) {
                val parent = if (variant == "occupied-parent") "a-local" else "z-local"
                val key = "attachment\u0000$parent\u0000old-file"
                input = input.copy(personalSync = input.personalSync.copy(entities = input.personalSync.entities +
                    (key to child!!.copy(parent_id = parent, state = "deleted", status = "resolved"))))
            }
            val digest = (PersonalSync.attachmentDescriptor(remoteFile)!!.descriptor["sha256"] as JsonPrimitive).content
            val result = PersonalSync.apply(input, b.second, mapOf(digest to remoteFile))
            if (format == 1 || variant != "same") {
                assertEquals("$format/$variant", 2, result.bestand.notizen.size)
                assertEquals(file, result.bestand.notizen.first { it.id == "z-local" }.anhaenge.single())
                continue
            }
            val reverse = PersonalSync.apply(b.first, a.second, mapOf(digest to file))
            assertEquals(0, result.conflicts); assertEquals(0, reverse.conflicts)
            assertEquals(file, result.bestand.notizen.single().anhaenge.single())
            val moved = result.bestand.personalSync.entities.getValue("attachment\u0000a-local\u0000file")
            assertEquals(child!!.hash, moved.hash); assertEquals("a-local", moved.parent_id)
            assertTrue(!moved.acknowledged_by_peer)
            assertTrue("attachment\u0000z-local\u0000file" !in result.bestand.personalSync.entities)
            val loaded = Json.Default.decodeFromString<Bestand>(Json.Default.encodeToString(result.bestand))
            val next = PersonalSync.reconcile(loaded, setOf("notes"), format, peer)
            val other = PersonalSync.reconcile(reverse.bestand, setOf("notes"), format, peer)
            assertEquals(next.second.single { it.kind == "note" }.hash, other.second.single { it.kind == "note" }.hash)
            assertTrue(next.first.personalSync.entities.values.none { it.state == "deleted" })
            val acknowledged = PersonalSync.acknowledge(next.first, peer)
            val removed = PapierkorbLogik.loescheAnhang(acknowledged, "z-local", "file", 2000)
            val deleted = PersonalSync.reconcile(removed, setOf("notes"), format, peer, 2000).first
            val proposal = PersonalSync.proposals(deleted, peer).single { it.kind == "attachment" }
            assertEquals("a-local", proposal.parent_id)
            val restored = PersonalSync.applyDeletionDecisions(deleted, listOf(
                AppliedPersonalDecision(proposal.proposal_id, "restore", proposal.clock)))
            assertEquals("applied", restored.second)
            assertEquals(file, restored.first.notizen.single().anhaenge.single())
            assertEquals("live", restored.first.personalSync.entities.getValue("attachment\u0000a-local\u0000file").state)
        }
    }

    @Test fun `legacy notebook timestamps normalize once and remain stable after replay and reload`() {
        val actor = "11111111-1111-4111-8111-111111111111"
        val peer = "22222222-2222-4222-8222-222222222222"
        for (format in listOf(1, 2, 3)) for (scenario in listOf("local-wins", "remote-wins", "dominated")) {
            val initial = PersonalSync.reconcile(Bestand(notizbuecher = listOf(Notizbuch("book", "Notebook")),
                personalSync = PersonalSyncState(actor_id = actor)), setOf("notes"), format, peer)
            val baseline = initial.second.single { it.id == "book" }
            val remote = (1L..1000L).map { date ->
                val value = JsonObject(baseline.value + ("modified_ms" to JsonPrimitive(date)))
                baseline.copy(value = value, hash = PersonalSync.hash(value), modifiedMs = date,
                    clock = (if (scenario == "dominated") baseline.clock else emptyList()) + PersonalSyncClock(peer, 1))
            }.first { scenario == "dominated" || (it.hash < baseline.hash) == (scenario == "remote-wins") }
            val result = PersonalSync.apply(initial.first, listOf(remote))
            assertEquals(0, result.conflicts)
            val normalized = PersonalSync.reconcile(result.bestand, setOf("notes"), format, peer)
            val expected = normalized.second.single { it.id == "book" }
            assertEquals(0L, expected.modifiedMs); assertEquals(baseline.hash, expected.hash)
            var state = Json.Default.decodeFromString<Bestand>(Json.Default.encodeToString(normalized.first))
            repeat(3) {
                val replay = PersonalSync.apply(state, listOf(remote))
                assertEquals(0, replay.conflicts); assertEquals(1, replay.bestand.notizbuecher.size)
                val next = PersonalSync.reconcile(replay.bestand, setOf("notes"), format, peer)
                assertEquals(expected, next.second.single { it.id == "book" }); state = next.first
            }
        }
    }

    @Test fun `independent plain note identities keep local IDs and converge on one wire ID`() {
        val peer = "33333333-3333-4333-8333-333333333333"
        for (format in listOf(1, 2, 3)) {
            fun initial(id: String, actor: String, time: Long) = PersonalSync.reconcile(
                Bestand(notizen = listOf(Notiz(id, titel = "Welcome", text = "Same", html = "Same", angelegt = time, geaendert = time)),
                    personalSync = PersonalSyncState(actor_id = actor)), setOf("notes"), format, peer)
            val a = initial("z-local", "11111111-1111-4111-8111-111111111111", 1)
            val b = initial("a-local", "22222222-2222-4222-8222-222222222222", 2)
            val mergedA = PersonalSync.apply(a.first, b.second)
            val mergedB = PersonalSync.apply(b.first, a.second)
            assertEquals(0, mergedA.conflicts); assertEquals(0, mergedB.conflicts)
            assertEquals("z-local", mergedA.bestand.notizen.single().id)
            assertEquals("a-local", mergedB.bestand.notizen.single().id)
            val nextA = PersonalSync.reconcile(mergedA.bestand, setOf("notes"), format, peer)
            val nextB = PersonalSync.reconcile(mergedB.bestand, setOf("notes"), format, peer)
            assertEquals("a-local", nextA.second.single { it.kind == "note" }.id)
            assertEquals(nextA.second.single { it.kind == "note" }.hash, nextB.second.single { it.kind == "note" }.hash)
            val loaded = Json.Default.decodeFromString<Bestand>(Json.Default.encodeToString(nextA.first))
            if (format >= 2) {
                val file = Anhang("file", "image.png", "image", ((contract["format2"] as JsonObject)["data_url"] as JsonPrimitive).content)
                val attached = PersonalSync.reconcile(loaded.copy(notizen = loaded.notizen.map { it.copy(anhaenge = listOf(file)) }),
                    setOf("notes"), format, peer).first
                val child = attached.personalSync.entities.getValue("attachment\u0000a-local\u0000file")
                val proposal = PersonalDeletionProposal("", "test", "attachment", "file", "a-local", child.clock, child.hash, 1000, "file")
                assertTrue(PersonalSync.matchesCurrent(attached, proposal))
                assertTrue(!PersonalSync.matchesCurrent(attached, proposal.copy(parent_id = "z-local")))
                val acknowledgedFiles = PersonalSync.acknowledge(attached, peer)
                val removedFile = PapierkorbLogik.loescheAnhang(acknowledgedFiles, "z-local", "file", 2000)
                val deletion = PersonalSync.reconcile(removedFile, setOf("notes"), format, peer, 2000).first
                assertEquals("a-local", PersonalSync.proposals(deletion, peer).single { it.kind == "attachment" }.parent_id)
                val restoredFile = PapierkorbLogik.wiederherstellen(deletion, deletion.papierkorb.single { it.art == "attachment" }.id)!!
                assertEquals(1, restoredFile.notizen.single().anhaenge.size)
                assertEquals("live", restoredFile.personalSync.entities.getValue("attachment\u0000a-local\u0000file").state)
            }
            val edited = loaded.copy(notizen = loaded.notizen.map { it.copy(text = "Edited", html = "Edited", geaendert = 1000) })
            val outgoing = PersonalSync.reconcile(edited, setOf("notes"), format, peer)
            val changedB = PersonalSync.apply(nextB.first, outgoing.second).bestand
            assertEquals("Edited", changedB.notizen.single().text)
            assertEquals("a-local", changedB.notizen.single().id)
            val replay = PersonalSync.apply(changedB, a.second).bestand
            assertEquals("Edited", replay.notizen.single().text)
            val acknowledged = PersonalSync.acknowledge(outgoing.first, peer)
            assertTrue(PersonalSync.proposals(PersonalSync.reconcile(acknowledged, setOf("notes"), format, peer).first, peer).isEmpty())
            val removed = PapierkorbLogik.loescheNotiz(acknowledged, "z-local", 2000)
            val deleted = PersonalSync.reconcile(removed, setOf("notes"), format, peer, 2000).first
            assertEquals(listOf("a-local"), PersonalSync.proposals(deleted, peer).filter { it.kind == "note" }.map { it.id })
            assertTrue(PersonalSync.apply(deleted, a.second).bestand.notizen.isEmpty())
            val restored = PapierkorbLogik.wiederherstellen(deleted, deleted.papierkorb.single { it.art == "note" }.id)!!
            assertEquals("z-local", restored.notizen.single().id)
            assertEquals("live", restored.personalSync.entities.getValue("note\u0000a-local").state)
            assertTrue("note\u0000a-local" in restored.personalSync.restoration_requests)
        }
    }

    @Test fun `malformed note identity maps fail closed`() {
        val cyclic = PersonalSyncState(note_ids = mapOf("local" to "a"), note_aliases = mapOf("a" to "b", "b" to "a"))
        assertTrue(runCatching { PersonalSync.noteWireId(cyclic, "local") }.isFailure)
        assertTrue(runCatching { PersonalSync.noteWireId(PersonalSyncState(note_ids = mapOf("local" to "")), "local") }.isFailure)
    }

    @Test fun `note timestamps alone converge without conflict copies`() {
        val actor = "11111111-1111-4111-8111-111111111111"
        val remoteActor = "22222222-2222-4222-8222-222222222222"
        val file = Anhang("attachment", "image.png", "image", ((contract["format2"] as JsonObject)["data_url"] as JsonPrimitive).content)
        for (format in listOf(1, 2, 3)) for (remoteWins in listOf(false, true)) {
            val note = Notiz("same-note", titel = "Welcome", text = "Same content", html = "Same content",
                angelegt = 1, geaendert = 10, anhaenge = listOf(file))
            val baseline = PersonalSync.reconcile(Bestand(notizen = listOf(note),
                personalSync = PersonalSyncState(actor_id = actor)), setOf("notes"), format)
            val local = baseline.second.single { it.kind == "note" }
            val remote = (0..100).map { index ->
                val value = JsonObject(local.value + mapOf("created_ms" to JsonPrimitive(100L + index),
                    "modified_ms" to JsonPrimitive(200L + index)))
                local.copy(value = value, hash = PersonalSync.hash(value), modifiedMs = 200L + index,
                    clock = listOf(PersonalSyncClock(remoteActor, 1)))
            }.first { (it.hash < local.hash) == remoteWins }
            val attachments = if (format >= 2) mapOf((PersonalSync.attachmentDescriptor(file)!!.descriptor["sha256"] as JsonPrimitive).content to file) else emptyMap()
            val result = PersonalSync.apply(baseline.first, listOf(remote), attachments)
            assertEquals(0, result.conflicts); assertEquals(1, result.bestand.notizen.size)
            assertEquals(1, result.bestand.notizen.single().anhaenge.size)
            val next = PersonalSync.reconcile(result.bestand, setOf("notes"), format)
            assertEquals(if (remoteWins) remote.hash else local.hash, next.second.single { it.kind == "note" }.hash)
            val repeated = PersonalSync.apply(next.first, listOf(remote), attachments)
            assertEquals(0, repeated.conflicts); assertEquals(1, repeated.bestand.notizen.size)
            val changedValue = JsonObject(remote.value + ("html" to JsonPrimitive("<b>Same content</b>")))
            val changed = remote.copy(value = changedValue, hash = PersonalSync.hash(changedValue),
                clock = listOf(PersonalSyncClock(remoteActor, 2)))
            val conflict = PersonalSync.apply(next.first, listOf(changed), attachments)
            assertEquals(1, conflict.conflicts); assertEquals(2, conflict.bestand.notizen.size)
        }
    }

    @Test fun `F31 format 1 fallback cannot infer an attachment deletion`() {
        val peer = "33333333-3333-4333-8333-333333333333"
        val note = Notiz("n", anhaenge = listOf(Anhang("a", "image.png", "image",
            "data:image/png;base64,iVBORw0KGgo=")))
        val baseline = PersonalSync.acknowledge(PersonalSync.reconcile(
            Bestand(notizen = listOf(note)), setOf("notes"), 3, peer).first, peer)
        val fallback = PersonalSync.reconcile(baseline, setOf("notes"), 1, peer).first
        assertEquals("live", fallback.personalSync.entities.getValue("attachment\u0000n\u0000a").state)
        assertTrue(PersonalSync.proposals(fallback, peer).isEmpty())
        val tasksOnly = PersonalSync.reconcile(baseline, setOf("tasks"), 3, peer).first
        assertEquals("live", tasksOnly.personalSync.entities.getValue("attachment\u0000n\u0000a").state)
    }

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

    @Test fun `Format 3 task golden und Formate 1 und 2 bleiben unveraendert`() {
        val parent = Aufgabe("parent", "Parent", uid = "parent-1")
        val task = Aufgabe("task-1", "Task", uid = "uid-1", elternUid = "parent-1", reihenfolge = 7)
        fun value(format: Int) = PersonalSync.reconcile(Bestand(aufgaben = listOf(parent, task)),
            setOf("tasks"), format).second.single { it.id == "task-1" }.value
        val format1 = value(1)
        val format2 = value(2)
        val format3 = value(3)
        assertEquals(format1, format2)
        assertTrue("uid" !in format1 && "parent_uid" !in format1 && "order" !in format1)
        assertEquals("uid-1", (format3["uid"] as JsonPrimitive).content)
        assertEquals("parent-1", (format3["parent_uid"] as JsonPrimitive).content)
        assertEquals("0", (format3["order"] as JsonPrimitive).content)
        assertEquals("{\"completed\":false,\"created_ms\":0,\"due\":\"\",\"lead_days\":0," +
            "\"modified_ms\":0,\"note\":\"\",\"order\":0,\"parent_uid\":\"parent-1\"," +
            "\"priority\":2,\"remind\":false,\"reminder_minute\":480,\"title\":\"Task\",\"uid\":\"uid-1\"}",
            PersonalSync.canonical(format3).decodeToString())
        assertEquals("68fa929056b339d8ec002a6c4c2c055c9193bd0b97722c6c2225f032ec121fef",
            PersonalSync.hash(format3))
        val actor = "11111111-1111-4111-8111-111111111111"
        val record = PersonalSyncRecord("task", "task-1", listOf(PersonalSyncClock(actor, 1)),
            PersonalSync.hash(format3), 0, format3)
        val decoded = PersonalSyncProtokoll.decodeBatch(PersonalSyncProtokoll.batch(
            actor, listOf(record), 0, true, false, 3, PersonalSync.recordsHash(listOf(record))))
        assertEquals(format3, decoded.single().value)
    }

    @Test fun `Task Konfliktkopie erhaelt neue id und uid`() {
        val first = "11111111-1111-4111-8111-111111111111"
        val second = "22222222-2222-4222-8222-222222222222"
        val local = Aufgabe("task", "Local", uid = "local-uid")
        val remoteValue = PersonalSync.reconcile(Bestand(aufgaben = listOf(
            Aufgabe("task", "Remote", uid = "remote-uid"))), setOf("tasks"), 3).second.single().value
        val input = Bestand(aufgaben = listOf(local), personalSync = PersonalSyncState(entities = mapOf(
            "task\u0000task" to PersonalSyncEntity(listOf(PersonalSyncClock(first, 1)), "f".repeat(64), 1))))
        val result = PersonalSync.apply(input, listOf(PersonalSyncRecord("task", "task",
            listOf(PersonalSyncClock(second, 1)), PersonalSync.hash(remoteValue), 0, remoteValue))).bestand.aufgaben
        assertEquals(2, result.size)
        assertEquals(2, result.map(Aufgabe::id).distinct().size)
        assertEquals(2, result.map(Aufgabe::uid).distinct().size)
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
        assertEquals("Alt", result.titel)
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
