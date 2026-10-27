package io.gitlab.maik3531.magnolienotes.daten

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.io.IOException
import javax.crypto.spec.SecretKeySpec

/** Actual encrypted document writes, synthetic key and paired peer identity. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PersonalActorDeletionSaveTest {
    private class Fixture {
        val context: Context = ApplicationProvider.getApplicationContext()
        var keyReads = 0
        var failWrites = false
        val storage: Ablage
        val file: File
        init {
            context.filesDir.listFiles()?.forEach { if (it.isDirectory) it.deleteRecursively() else it.delete() }
            storage = Ablage.fuerTest(context) {
                keyReads++
                if (failWrites) throw IOException("Synthetic writer failure")
                SecretKeySpec(ByteArray(32) { 19 }, "AES")
            }
            storage.setzeNotiz(Notiz("a", "A", "First private value"))
            storage.setzeNotiz(Notiz("b", "B", "Second private value"))
            storage.personalSyncSnapshot(setOf("notes"), 3)
            file = File(context.filesDir, "notizen.json")
        }
        fun review(): Pair<List<PersonalDeletionProposal>, List<AppliedPersonalDecision>> {
            val records = storage.personalSyncSnapshot(setOf("notes"), 3).filter { it.kind == "note" && it.id in setOf("a", "b") }
            val proposals = records.mapIndexed { index, record -> PersonalDeletionProposal(RUN, id(index + 10), "note", record.id,
                clock = (record.clock + PersonalSyncClock(PEER, 1)).sortedBy { it.actor_id }, prior_hash = record.hash,
                deleted_ms = 1700000000000, source_device = PEER, label = "Synthetic") }
            return proposals to proposals.mapIndexed { index, value -> AppliedPersonalDecision(value.proposal_id, "delete", value.clock, id(index + 20)) }
        }
        fun apply(proposals: List<PersonalDeletionProposal>, choices: List<AppliedPersonalDecision>,
            after: PersonalContentSelection, beforeBook: Bestand = storage.bestand.value): String = storage.personalSyncApplyActorDeletionOnce(
                PEER, RUN, TOKEN, beforeBook, PersonalSync.livePersonalContent(beforeBook), after, proposals, choices, emptyList())
    }

    @Test fun completeReviewUsesOneEncryptedWriteAndReplayUsesNone() {
        val f = Fixture(); val (proposals, choices) = f.review()
        val before = f.storage.bestand.value; val live = PersonalSync.livePersonalContent(before)
        val after = live.copy(notes = live.notes - setOf("a", "b")); val reads = f.keyReads
        assertEquals("applied", f.apply(proposals, choices, after, before))
        assertEquals(1, f.keyReads - reads)
        assertNull(f.storage.notiz("a")); assertNull(f.storage.notiz("b"))
        assertEquals(2, f.storage.bestand.value.personalSync.pending_decisions.count { it.run_id == RUN })
        val reopened = Ablage.fuerTest(f.context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        assertNull(reopened.notiz("a")); assertNull(reopened.notiz("b"))
        assertTrue(TOKEN in reopened.bestand.value.personalSync.applied_batches)
        val saved = f.file.readBytes(); val savedReads = f.keyReads
        assertEquals("applied", f.apply(proposals, choices, after, before))
        assertEquals(savedReads, f.keyReads); assertArrayEquals(saved, f.file.readBytes())
    }

    @Test fun laterConflictDoesNotSaveEarlierDeletionOrReconciliation() {
        val f = Fixture(); val (proposals, choices) = f.review(); val before = f.storage.bestand.value
        val changed = proposals.mapIndexed { index, value -> if (index == 1) value.copy(prior_hash = "b".repeat(64)) else value }
        val bytes = f.file.readBytes(); val reads = f.keyReads
        assertEquals("conflict", f.apply(changed, choices, PersonalSync.livePersonalContent(before).copy(notes = emptySet()), before))
        assertSame(before, f.storage.bestand.value); assertEquals(reads, f.keyReads); assertArrayEquals(bytes, f.file.readBytes())
        assertNotNull(f.storage.notiz("a")); assertNotNull(f.storage.notiz("b"))
    }

    @Test fun staleBookOrUnexpectedScopeDoesNotWriteAnyPreview() {
        val f = Fixture(); val (proposals, choices) = f.review(); val before = f.storage.bestand.value
        val bytes = f.file.readBytes(); val reads = f.keyReads
        assertEquals("conflict", f.apply(proposals, choices, PersonalContentSelection(setOf("foreign"), emptySet()), before))
        assertEquals("conflict", f.apply(proposals, choices, PersonalContentSelection(emptySet(), emptySet()), before.copy()))
        assertEquals(reads, f.keyReads); assertArrayEquals(bytes, f.file.readBytes()); assertSame(before, f.storage.bestand.value)
    }

    @Test fun actualWriteFailureLeavesBookAndDiskAtTheOriginalState() {
        val f = Fixture(); val (proposals, choices) = f.review(); val before = f.storage.bestand.value
        val bytes = f.file.readBytes(); f.failWrites = true
        assertTrue(runCatching { f.apply(proposals, choices, PersonalSync.livePersonalContent(before).copy(notes = emptySet()), before) }.isFailure)
        assertSame(before, f.storage.bestand.value); assertArrayEquals(bytes, f.file.readBytes())
        f.failWrites = false
        assertNotNull(f.storage.notiz("a")); assertNotNull(f.storage.notiz("b"))
    }

    @Test fun acknowledgedRestoreUsesExistingTrashAndOneDurableWrite() {
        val f = Fixture(); f.storage.personalSyncAcknowledge(PEER)
        f.storage.loescheNotiz("a"); f.storage.personalSyncSnapshot(setOf("notes"), 3)
        val before = f.storage.bestand.value
        val proposal = PersonalSync.proposals(before, PEER).single { it.kind == "note" && it.id == "a" }
        val proof = AppliedPersonalDecision(proposal.proposal_id, "restore", proposal.clock, id(30))
        val live = PersonalSync.livePersonalContent(before); val after = live.copy(notes = live.notes + "a"); val reads = f.keyReads
        assertEquals("applied", f.storage.personalSyncApplyActorDeletionOnce(PEER, RUN, TOKEN, before, live, after,
            emptyList(), emptyList(), listOf(proof)))
        assertEquals(1, f.keyReads - reads); assertNotNull(f.storage.notiz("a"))
        val reopened = Ablage.fuerTest(f.context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        assertNotNull(reopened.notiz("a")); assertTrue(proof in reopened.bestand.value.personalSync.applied_decision_proofs)
    }

    companion object {
        private const val PEER = "11111111-1111-4111-8111-111111111111"
        private const val RUN = "22222222-2222-4222-8222-222222222222"
        private const val TOKEN = "native-actor-terminal-fixture"
        private fun id(value: Int) = "%08x-0000-4000-8000-%012x".format(value, value)
    }
}
