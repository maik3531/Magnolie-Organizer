package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.*
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class PersonalRestoreMetadataTest {
    private val peer = "22222222-2222-4222-8222-222222222222"
    private val run = "44444444-4444-4444-8444-444444444444"
    private fun pending(kind: String): Triple<Bestand, PersonalDeletionProposal, String> {
        val fixture = Json.parseToJsonElement(requireNotNull(javaClass.getResource("/personal-sync-contract.json")).readText()).jsonObject
        val image = fixture.getValue("format2").jsonObject.getValue("data_url").jsonPrimitive.content
        val input = Bestand(notizen = listOf(Notiz("own-note", text = "Synthetic original",
            anhaenge = listOf(Anhang("own-file", "sample.png", "image", image)))),
            aufgaben = listOf(Aufgabe("own-task", titel = "Synthetic original task")))
        val live = PersonalSync.acknowledge(PersonalSync.reconcile(input, setOf("notes", "tasks"), 3, peer).first, peer)
        val removed = when (kind) { "note" -> PapierkorbLogik.loescheNotiz(live, "own-note")
            "task" -> PapierkorbLogik.loescheAufgabe(live, "own-task")
            else -> PapierkorbLogik.loescheAnhang(live, "own-note", "own-file") }
        val pending = PersonalSync.reconcile(removed, setOf("notes", "tasks"), 3, peer).first
        val id = when (kind) { "note" -> "own-note"; "task" -> "own-task"; else -> "own-file" }
        val parent = if (kind == "attachment") "own-note" else ""
        val key = kind + "\u0000" + (if (parent.isEmpty()) "" else parent + "\u0000") + id
        val meta = pending.personalSync.entities.getValue(key)
        assertEquals("deleted", meta.state); assertEquals("local_pending", meta.status)
        val proposal = PersonalDeletionProposal(run, UUID.randomUUID().toString(), kind, id, parent, meta.clock,
            meta.prior_hash, meta.deleted_ms, "Synthetic remote proposal", peer)
        return Triple(PersonalSync.stageProposals(pending, run, peer, listOf(proposal)), proposal, key)
    }

    private fun restoresLiveMetadata(kind: String) {
        val (input, proposal, key) = pending(kind)
        val old = input.personalSync.entities.getValue(key); val decision = UUID.randomUUID().toString()
        val (restored, result) = PersonalSync.decideDeletion(input, peer, proposal.proposal_id, decision, "restore")
        assertEquals("applied", result)
        val live = restored.personalSync.entities.getValue(key)
        assertEquals("Restored content must not retain the old deleted sync entity", "live", live.state)
        assertEquals("restored", live.status); assertEquals("", live.proposal_id)
        assertEquals("dominates", PersonalSync.compare(live.clock, old.clock))
        assertTrue(restored.personalSync.counter > input.personalSync.counter)
        assertTrue(key in restored.personalSync.restoration_requests)
        val (snapshotted, records) = PersonalSync.reconcile(restored, setOf("notes", "tasks"), 3, peer)
        assertEquals("live", snapshotted.personalSync.entities.getValue(key).state)
        assertEquals(64, snapshotted.personalSync.entities.getValue(key).hash.length)
        if (kind == "attachment") assertTrue(records.single { it.kind == "note" && it.id == "own-note" }.value
            .getValue("attachments").jsonArray.any { it.jsonObject.stringValue("attachment_id") == "own-file" })
        else assertTrue(records.any { it.kind == kind && it.id == proposal.id })
        val retry = PersonalSync.decideDeletion(restored, peer, proposal.proposal_id, decision, "restore")
        assertEquals("applied", retry.second); assertSame(restored, retry.first)
        assertEquals(input.zeiterfassung, restored.zeiterfassung)
    }

    @Test fun restoringANotePreservesFreshLiveMetadataAndTheNextSnapshot() = restoresLiveMetadata("note")
    @Test fun restoringATaskPreservesFreshLiveMetadataAndTheNextSnapshot() = restoresLiveMetadata("task")
    @Test fun restoringAnAttachmentPreservesFreshLiveMetadataAndTheNextSnapshot() = restoresLiveMetadata("attachment")

    @Test fun aMissingLocalTrashSourceStillCannotBeInventedByRestore() {
        val (pending, proposal, _) = pending("note")
        val input = pending.copy(papierkorb = emptyList())
        val (next, result) = PersonalSync.decideDeletion(input, peer, proposal.proposal_id, UUID.randomUUID().toString(), "restore")
        assertEquals("restore_unavailable", result)
        assertEquals(input.notizen, next.notizen); assertEquals(input.aufgaben, next.aufgaben)
        assertEquals(input.personalSync.applied_decision_proofs, next.personalSync.applied_decision_proofs)
    }

    private fun JsonObject.stringValue(key: String) = getValue(key).jsonPrimitive.content
}
