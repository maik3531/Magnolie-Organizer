package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.*
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

/** Local preparation only, not a service-origin/save/terminal capability. */
class PersonalHistoricalRestoreClaimTest {
    private val peer = "22222222-2222-4222-8222-222222222222"
    private val run = "44444444-4444-4444-8444-444444444444"
    private val saved = buildJsonObject { put("book_source", "b".repeat(64)); put("sequence", 7); put("sha256", "c".repeat(64)) }
    private data class Fixture(val book: Bestand, val proposal: PersonalDeletionProposal, val choice: AppliedPersonalDecision)
    private fun fixture(kind: String = "note"): Fixture {
        val live = PersonalSync.acknowledge(PersonalSync.reconcile(Bestand(
            notizen = listOf(Notiz("own-note", text = "Synthetic original")), aufgaben = listOf(Aufgabe("own-task", titel = "Synthetic task"))),
            setOf("notes", "tasks"), 3, peer).first, peer)
        val removed = if (kind == "note") PapierkorbLogik.loescheNotiz(live, "own-note") else PapierkorbLogik.loescheAufgabe(live, "own-task")
        val book = PersonalSync.reconcile(removed, setOf("notes", "tasks"), 3, peer).first
        val id = if (kind == "note") "own-note" else "own-task"; val meta = book.personalSync.entities.getValue(kind + "\u0000" + id)
        val proposal = PersonalDeletionProposal(run, UUID.randomUUID().toString(), kind, id, "", meta.clock, meta.prior_hash, meta.deleted_ms, "Synthetic", peer)
        return Fixture(book, proposal, AppliedPersonalDecision(proposal.proposal_id, "restore", proposal.clock, UUID.randomUUID().toString()))
    }
    private fun prepare(f: Fixture, selection: PersonalContentSelection = PersonalSync.livePersonalContent(f.book)) =
        PersonalHistoricalRestoreClaim.prepare(peer, run, f.book, saved, selection, listOf(f.proposal), listOf(f.choice))

    @Test fun aPreparedHistoricalRestoreAddsOnlyItsExactLocalTargetToLiveStateButNotToItsBeforeDataSelection() {
        for (kind in listOf("note", "task")) {
            val f = fixture(kind); val selection = PersonalSync.livePersonalContent(f.book)
            val claim = prepare(f)
            assertSame(f.book, claim.beforeBook); assertEquals(saved, claim.beforeSavedBook); assertEquals(selection, claim.beforeLive)
            assertEquals(PersonalSync.livePersonalContent(claim.afterBook), claim.afterLive)
            assertEquals("live", claim.afterBook.personalSync.entities.getValue(kind + "\u0000" + f.proposal.id).state)
            assertTrue(claim.batchKey in claim.afterBook.personalSync.applied_batches)
            assertFalse(f.proposal.id in (if (kind == "note") selection.notes else selection.tasks))
            assertTrue(f.proposal.id in (if (kind == "note") claim.afterLive.notes else claim.afterLive.tasks))
            assertEquals(f.book.zeiterfassung, claim.afterBook.zeiterfassung)
        }
    }

    @Test fun missingAmbiguousForeignOrChangedLocalTrashCannotBecomeAnAcceptedBatchFallback() {
        for (kind in listOf("note", "task")) for (fault in listOf("missing", "duplicate", "foreign", "changed", "id-collision")) {
            val f = fixture(kind); val source = f.book.papierkorb.single()
            val changed = when (fault) {
                "missing" -> emptyList()
                "duplicate" -> listOf(source, source.copy(id = UUID.randomUUID().toString()))
                "id-collision" -> listOf(source, if (kind == "note") source.copy(art = "task", notiz = null, aufgabe = Aufgabe("unrelated-trash"))
                    else source.copy(art = "note", aufgabe = null, notiz = Notiz("unrelated-trash")))
                else -> listOf(if (kind == "note") source.copy(notiz = source.notiz!!.copy(
                    text = if (fault == "changed") "Substituted source" else source.notiz.text,
                    baumQuelle = if (fault == "foreign") "foreign" else ""))
                    else source.copy(aufgabe = source.aufgabe!!.copy(titel = if (fault == "changed") "Substituted source" else source.aufgabe.titel,
                        delegiertAn = if (fault == "foreign") "foreign" else "")))
            }
            assertTrue("$kind/$fault", runCatching { prepare(f.copy(book = f.book.copy(papierkorb = changed))) }.isFailure)
        }
    }

    @Test fun staleSelectionResolvedMetadataAndUnconfirmedKindsOrChangedClocksCannotPrepareARestore() {
        val f = fixture()
        assertTrue(runCatching { prepare(f, PersonalContentSelection(setOf("foreign"), emptySet())) }.isFailure)
        val meta = f.book.personalSync.entities.getValue("note\u0000own-note")
        assertTrue(runCatching { prepare(f.copy(book = f.book.copy(personalSync = f.book.personalSync.copy(entities =
            f.book.personalSync.entities + ("note\u0000own-note" to meta.copy(status = "resolved")))))) }.isFailure)
        assertTrue(runCatching { prepare(f.copy(choice = f.choice.copy(decision = "delete"))) }.isFailure)
        assertTrue(runCatching { prepare(f.copy(choice = f.choice.copy(expected_clock = listOf(PersonalSyncClock(peer, 999))))) }.isFailure)
        val changedClock = listOf(PersonalSyncClock(peer, 999))
        assertTrue(runCatching { prepare(f.copy(proposal = f.proposal.copy(clock = changedClock), choice = f.choice.copy(expected_clock = changedClock))) }.isFailure)
        assertTrue(runCatching { prepare(f.copy(proposal = f.proposal.copy(prior_hash = "f".repeat(64)))) }.isFailure)
        assertTrue(runCatching { prepare(f.copy(proposal = f.proposal.copy(source_device = run))) }.isFailure)
        assertTrue(runCatching { prepare(f.copy(proposal = f.proposal.copy(kind = "attachment", parent_id = "parent"))) }.isFailure)
    }
}
