package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class PersonalScopeProjectionTest {
    private val peer = "22222222-2222-4222-8222-222222222222"
    private fun fixture() = Bestand(
        notizen = listOf(Notiz("local-note", "Mobile", "Original", notizbuchId = "shared-book"),
            Notiz("organizer-only", "Private", "Do not project", notizbuchId = "private-book")),
        aufgaben = listOf(Aufgabe("mobile-task", "Shared task"), Aufgabe("organizer-task", "Private task")),
        notizbuecher = listOf(Notizbuch("shared-book", "Shared"), Notizbuch("private-book", "Private")),
        personalSync = PersonalSyncState(actor_id = "11111111-1111-4111-8111-111111111111",
            note_ids = mapOf("local-note" to "wire-note")))

    @Test fun selectedWireIdentitiesAreProjectedBeforeUnrelatedContentsAndClocks() {
        val input = fixture()
        val selection = PersonalContentSelection(setOf("wire-note"), setOf("mobile-task"))
        val (state, records) = PersonalSync.reconcile(input, setOf("notes", "tasks"), 3, peer, selection = selection)
        assertEquals(setOf("note:wire-note", "task:mobile-task", "notebook:shared-book"), records.map { "${it.kind}:${it.id}" }.toSet())
        assertFalse(state.personalSync.entities.containsKey("note\u0000organizer-only"))
        assertFalse(state.personalSync.entities.containsKey("task\u0000organizer-task"))
        assertFalse(state.personalSync.entities.containsKey("notebook\u0000private-book"))
        assertEquals(input.notizen, state.notizen)
        assertEquals(input.aufgaben, state.aufgaben)
    }

    @Test fun liveMembershipUsesPhysicalObjectsAndExistingWireAliasesRatherThanGhostMetadata() {
        val input = fixture().let { it.copy(personalSync = it.personalSync.copy(entities = mapOf(
            "note\u0000ghost" to PersonalSyncEntity(state = "live"), "task\u0000ghost-task" to PersonalSyncEntity(state = "live")))) }
        val live = PersonalSync.livePersonalContent(input)
        assertEquals(setOf("wire-note", "organizer-only"), live.notes)
        assertEquals(setOf("mobile-task", "organizer-task"), live.tasks)
        assertFalse("ghost" in live.notes || "ghost-task" in live.tasks)
    }

    @Test fun independentPhysicalRemovalDoesNotGenerateRemoteDeletionAndLegacyBehaviorIsPreserved() {
        val initial = PersonalSync.reconcile(fixture(), setOf("notes", "tasks"), 3, peer).first
        val confirmed = PersonalSync.acknowledge(initial, peer)
        val removed = confirmed.copy(notizen = emptyList(), aufgaben = emptyList())
        val result = PersonalSync.reconcile(removed, setOf("notes", "tasks"), 3, peer,
            selection = PersonalContentSelection(emptySet(), emptySet()), independentRemovals = true)
        assertTrue(result.second.isEmpty())
        assertEquals(confirmed.personalSync.entities["note\u0000wire-note"], result.first.personalSync.entities["note\u0000wire-note"])
        assertEquals(confirmed.personalSync.entities["task\u0000mobile-task"], result.first.personalSync.entities["task\u0000mobile-task"])
        assertTrue(PersonalSync.proposals(result.first, peer).none { it.kind == "note" || it.kind == "task" })
        val legacy = PersonalSync.reconcile(removed, setOf("notes", "tasks"), 3, peer).first
        assertEquals("deleted", legacy.personalSync.entities.getValue("note\u0000wire-note").state)
        assertEquals("deleted", legacy.personalSync.entities.getValue("task\u0000mobile-task").state)
    }

    @Test fun organizerAdditionToAnExistingSelectedNoteAppliesBackToThePhysicalPhoneCopy() {
        val input = fixture(); val selection = PersonalContentSelection(setOf("wire-note"), emptySet())
        val (state, records) = PersonalSync.reconcile(input, setOf("notes"), 3, peer, selection = selection, independentRemovals = true)
        val old = records.first { it.kind == "note" }
        val value = JsonObject(old.value + mapOf("text" to JsonPrimitive("Organizer addition"), "modified_ms" to JsonPrimitive(1000L)))
        val incoming = old.copy(value = value, hash = PersonalSync.hash(value), modifiedMs = 1000L,
            clock = (old.clock + PersonalSyncClock(peer, 1)).sortedBy { it.actor_id })
        val result = PersonalSync.applyScoped(state, listOf(incoming), PersonalSync.livePersonalContent(state), peer)
        assertEquals("Organizer addition", result.bestand.notizen.first { it.id == "local-note" }.text)
        assertEquals(input.notizen.first { it.id == "organizer-only" }, result.bestand.notizen.first { it.id == "organizer-only" })
        assertEquals(input.notizen.size, result.bestand.notizen.size)
        assertEquals(1, result.received)
    }

    @Test fun removedPhoneCopyAndUnrelatedIncomingRecordsAreRejectedAtCommitBoundary() {
        val (state, records) = PersonalSync.reconcile(fixture(), setOf("notes", "tasks"), 3, peer)
        val expected = PersonalSync.livePersonalContent(state)
        val removed = state.copy(notizen = state.notizen.filterNot { it.id == "local-note" })
        assertTrue(runCatching { PersonalSync.applyScoped(removed, records, expected, peer) }.isFailure)
        val note = records.first { it.kind == "note" }
        assertTrue(runCatching { PersonalSync.applyScoped(state, listOf(note.copy(id = "not-present")), expected, peer) }.isFailure)
        val task = records.first { it.kind == "task" }
        assertTrue(runCatching { PersonalSync.applyScoped(state, listOf(task.copy(id = "not-present")), expected, peer) }.isFailure)
        val book = records.first { it.kind == "notebook" }
        assertTrue(runCatching { PersonalSync.applyScoped(state, listOf(book), expected, peer) }.isFailure)
        assertTrue(runCatching { PersonalSync.applyScoped(state, listOf(note, note), expected, peer) }.isFailure)
        assertEquals(fixture().notizen, state.notizen)
    }
}
