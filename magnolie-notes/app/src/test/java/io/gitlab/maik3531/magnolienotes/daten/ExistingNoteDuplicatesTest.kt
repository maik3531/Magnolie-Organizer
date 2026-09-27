package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.encodeToString
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ExistingNoteDuplicatesTest {
    private val actor = "11111111-1111-4111-8111-111111111111"
    private val peer = "22222222-2222-4222-8222-222222222222"
    private val original = Notiz("z-local", titel = "Welcome", text = "Same content", html = "", angelegt = 1, geaendert = 1)
    private fun snapshot(input: Bestand) = PersonalSync.reconcile(input, setOf("notes"), 3, peer)

    @Test fun `equivalent notebooks bind before note identity across formats and restart`() {
        for (format in 1..3) {
            fun state(id: String, book: String, owner: String) = PersonalSync.reconcile(Bestand(
                notizbuecher = listOf(Notizbuch(book, "Shared name")),
                notizen = listOf(original.copy(id = id, notizbuchId = book,
                    html = if (owner == peer) "<p>Same content</p>" else "")),
                personalSync = PersonalSyncState(actor_id = owner)), setOf("notes"), format, peer)
            val left = state("z-note", "z-book", actor)
            val right = state("a-note", "a-book", peer)
            val merged = PersonalSync.apply(left.first, right.second)
            assertEquals(0, merged.conflicts)
            assertEquals("z-book", merged.bestand.notizbuecher.single().id)
            assertEquals("z-note", merged.bestand.notizen.single().id)
            assertEquals("z-book", merged.bestand.notizen.single().notizbuchId)
            val loaded = Json.decodeFromString<Bestand>(Json.encodeToString(merged.bestand))
            val outgoing = PersonalSync.reconcile(loaded, setOf("notes"), format, peer)
            assertEquals("a-book", outgoing.second.single { it.kind == "notebook" }.id)
            assertEquals("a-note", outgoing.second.single { it.kind == "note" }.id)
            val returned = PersonalSync.apply(right.first, outgoing.second)
            assertEquals(0, returned.conflicts)
            assertEquals(1, returned.bestand.notizen.size)
            assertEquals(1, returned.bestand.notizbuecher.size)
            val proposal = PersonalDeletionProposal("run", "proposal", "notebook", "a-book",
                clock = emptyList(), prior_hash = "", deleted_ms = 100)
            assertEquals(PersonalDeletionPrompt.BLOCKED, PersonalDeletionDecisions().prompt(loaded, proposal))
            val empty = PersonalSync.acknowledge(PersonalSync.reconcile(loaded.copy(notizen = emptyList()),
                setOf("notes"), format, peer).first, peer)
            val deleted = PersonalSync.reconcile(PapierkorbLogik.loescheNotizbuch(empty, "z-book", 200)!!,
                setOf("notes"), format, peer).first
            val deletion = PersonalSync.proposals(deleted, peer).single { it.kind == "notebook" }
            assertEquals("a-book", deletion.id)
            val restored = PersonalSync.applyDeletionDecisions(deleted, listOf(
                AppliedPersonalDecision(deletion.proposal_id, "restore", deletion.clock)))
            assertEquals("applied", restored.second)
            assertEquals("z-book", restored.first.notizbuecher.single().id)
        }
    }

    @Test fun `ambiguous notebook names are not assigned to an arbitrary local book`() {
        val local = snapshot(Bestand(notizbuecher = listOf(Notizbuch("left", "Same"), Notizbuch("right", "Same")),
            personalSync = PersonalSyncState(actor_id = actor))).first
        val remote = snapshot(Bestand(notizbuecher = listOf(Notizbuch("remote", "Same")),
            personalSync = PersonalSyncState(actor_id = peer)))
        val result = PersonalSync.apply(local, remote.second).bestand
        assertEquals(3, result.notizbuecher.size)
        assertTrue(result.personalSync.notebook_aliases.isEmpty())
    }

    @Test fun `existing own and shared copies keep local identity scope and future edits`() {
        val initial = snapshot(Bestand(notizen = listOf(original), personalSync = PersonalSyncState(actor_id = actor))).first
        val shared = original.copy(baumQuelle = "tree-peer", baumFreigabe = Freigabe("share", listOf("tree-peer"),
            quellen = listOf(NotizQuelle("tree-peer", "share", 7, "tree-peer", 0))))
        val input = initial.copy(notizen = listOf(shared, original.copy(id = "a-duplicate", angelegt = 123)))
        assertEquals(2, snapshot(input).first.notizen.size)
        val remote = snapshot(Bestand(notizen = listOf(original), personalSync = PersonalSyncState(actor_id = peer)))
        val result = PersonalSync.apply(input, remote.second)
        assertEquals(0, result.conflicts)
        assertEquals("z-local", result.bestand.notizen.single().id)
        assertTrue(result.bestand.notizen.single().persoenlichVerknuepft)
        assertEquals(shared.baumFreigabe, result.bestand.notizen.single().baumFreigabe)
        assertFalse(result.bestand.personalSync.entities.values.any { it.state == "deleted" })
        val next = snapshot(result.bestand)
        assertEquals(1, next.second.count { it.kind == "note" })
        val other = PersonalSync.apply(remote.first, next.second).bestand
        val edited = snapshot(other.copy(notizen = other.notizen.map { it.copy(text = "Follow-up", geaendert = 200) }))
        val loaded = Json.decodeFromString<Bestand>(Json.encodeToString(next.first))
        val applied = PersonalSync.apply(loaded, edited.second)
        assertEquals("Follow-up", applied.bestand.notizen.single().text)
        assertEquals("Follow-up", PersonalSync.apply(applied.bestand, remote.second).bestand.notizen.single().text)
        val acknowledged = PersonalSync.acknowledge(snapshot(applied.bestand).first, peer)
        val removed = snapshot(PapierkorbLogik.loescheNotiz(acknowledged, "z-local", 300)).first
        val proposal = PersonalSync.proposals(removed, peer).single { it.kind == "note" }
        assertEquals("a-duplicate", proposal.id)
        val restored = PersonalSync.applyDeletionDecisions(removed, listOf(
            AppliedPersonalDecision(proposal.proposal_id, "restore", proposal.clock)))
        assertEquals("applied", restored.second)
        assertEquals("z-local", restored.first.notizen.single().id)
        assertEquals(shared.baumFreigabe, restored.first.notizen.single().baumFreigabe)
    }

    @Test fun `tree only duplicates retain both source clocks and never enter personal sync`() {
        val first = original.copy(baumQuelle = "a", baumInhaltVersion = 3,
            baumFreigabe = Freigabe("share-a", listOf("a"), listOf("a"), listOf(NotizQuelle("a", "share-a", 7, "a", 3))))
        val second = original.copy(id = "a-duplicate", baumQuelle = "b", baumInhaltVersion = 5,
            baumFreigabe = Freigabe("share-b", listOf("b"), emptyList(), listOf(NotizQuelle("b", "share-b", 12, "b", 4))))
        val input = Bestand(notizen = listOf(first, second), personalSync = PersonalSyncState(actor_id = actor))
        val result = PersonalSync.apply(input, emptyList(), mergeNotes = true).bestand
        val note = result.notizen.single()
        assertFalse(note.persoenlichVerknuepft)
        assertEquals(3L, note.baumFreigabe!!.quellen.single { it.partner == "a" }.stand)
        assertEquals(-1L, note.baumFreigabe.quellen.single { it.partner == "b" }.stand)
        assertEquals(0, snapshot(result).second.count { it.kind == "note" })
        assertEquals(result, PersonalSync.apply(result, emptyList(), mergeNotes = true).bestand)
    }

    @Test fun `real differences deletion history and restore requests prevent compaction`() {
        for (variant in listOf("text", "html", "book", "deleted", "restore", "proposal")) {
            var second = original.copy(id = "a-duplicate", angelegt = 123)
            second = when (variant) {
                "text" -> second.copy(text = "Different")
                "html" -> second.copy(html = "<b>Same content</b>")
                "book" -> second.copy(notizbuchId = "different-book")
                else -> second
            }
            var input = snapshot(Bestand(notizen = listOf(original, second), personalSync = PersonalSyncState(actor_id = actor))).first
            val state = input.personalSync
            input = input.copy(personalSync = when (variant) {
                "deleted" -> state.copy(entities = state.entities + ("attachment\u0000a-duplicate\u0000old-file" to PersonalSyncEntity(state = "deleted")))
                "restore" -> state.copy(restoration_requests = listOf("note\u0000a-duplicate"))
                "proposal" -> state.copy(pending_proposals = listOf(PersonalDeletionProposal("run", "proposal", "note", "a-duplicate",
                    clock = state.entities.getValue("note\u0000a-duplicate").clock, prior_hash = "", deleted_ms = 1)))
                else -> state
            })
            assertEquals(variant, input, PersonalSync.apply(input, emptyList(), mergeNotes = true).bestand)
        }
    }
}
