package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertEquals
import org.junit.Test

class PersonalDeletionReplayTest {
    @Test fun `revoking one computer preserves other computer and module decisions`() {
        fun proposal(peer: String, kind: String) = PersonalDeletionProposal("run-$peer", "$peer-$kind", kind, "same-object",
            clock = emptyList(), prior_hash = "hash", deleted_ms = 1, source_device = peer)
        val proposals = listOf(proposal("home", "note"), proposal("home", "task"), proposal("office", "note"))
        val decisions = proposals.map { PendingPersonalDecision(it.source_device, it.run_id, "decision-${it.proposal_id}",
            it.proposal_id, "restore", emptyList()) }
        val state = PersonalSyncState(pending_proposals = proposals, pending_decisions = decisions)
        val scoped = PersonalSync.revokeDeletionConsent(state, "home", setOf("note", "notebook", "attachment"))
        assertEquals(proposals.drop(1), scoped.pending_proposals)
        assertEquals(decisions.drop(1), scoped.pending_decisions)
        val allHome = PersonalSync.revokeDeletionConsent(state, "home")
        assertEquals(listOf(proposals.last()), allHome.pending_proposals)
        assertEquals(listOf(decisions.last()), allHome.pending_decisions)
        assertEquals(state, PersonalSync.revokeDeletionConsent(state, null))
        val committed = state.copy(pending_proposals = emptyList(), entities = mapOf(
            "note\u0000same-object" to PersonalSyncEntity(peer_device_id = "home", proposal_id = "home-note")))
        assertEquals(decisions.drop(1), PersonalSync.revokeDeletionConsent(committed, "home", setOf("note")).pending_decisions)
    }

    @Test fun `restore aliased note ignores later trash of another kind with the same wire ID`() {
        val actor = "11111111-1111-4111-8111-111111111111"
        val peer = "22222222-2222-4222-8222-222222222222"
        val initial = Bestand(notizen = listOf(Notiz("z-local", titel = "Retained note")),
            aufgaben = listOf(Aufgabe("a-wire", titel = "Unrelated task")),
            personalSync = PersonalSyncState(actor_id = actor,
                note_ids = mapOf("z-local" to "a-wire"), note_aliases = mapOf("z-local" to "a-wire")))
        val live = PersonalSync.acknowledge(PersonalSync.reconcile(initial, setOf("notes"), 3, peer).first, peer)
        val removed = PapierkorbLogik.loescheNotiz(live, "z-local", 2000)
        val deleted = PersonalSync.reconcile(removed, setOf("notes"), 3, peer, 2000).first
        val mixedTrash = PapierkorbLogik.loescheAufgabe(deleted, "a-wire", 3000)
        val proposal = PersonalSync.proposals(mixedTrash, peer).single { it.kind == "note" }
        val decision = AppliedPersonalDecision(proposal.proposal_id, "restore", proposal.clock)
        val (restored, status) = PersonalSync.applyDeletionDecisions(mixedTrash, listOf(decision))
        assertEquals("applied", status)
        assertEquals(listOf("z-local"), restored.notizen.map { it.id })
        assertEquals(emptyList<Aufgabe>(), restored.aufgaben)
        assertEquals(listOf("task"), restored.papierkorb.map { it.art })
        assertEquals("live", restored.personalSync.entities.getValue("note\u0000a-wire").state)
        assertEquals(restored to "applied", PersonalSync.applyDeletionDecisions(restored, listOf(decision)))

        val missing = mixedTrash.copy(papierkorb = mixedTrash.papierkorb.filter { it.art != "note" })
        assertEquals(missing to "restore_unavailable", PersonalSync.applyDeletionDecisions(missing, listOf(decision)))
    }

    private val clock = listOf(PersonalSyncClock("11111111-1111-4111-8111-111111111111", 2))
    private val first = AppliedPersonalDecision("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "delete", clock)
    private val second = AppliedPersonalDecision("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "delete", clock)

    private fun bestand() = Bestand(personalSync = PersonalSyncState(entities = mapOf(
        "note\u0000a" to PersonalSyncEntity(clock = clock, proposal_id = first.proposal_id, status = "pending"),
        "note\u0000b" to PersonalSyncEntity(clock = clock, proposal_id = second.proposal_id, status = "pending")
    )))

    @Test fun `multi decision staging is atomic and replay tuple is immutable`() {
        val input = bestand()
        val badClock = second.copy(expected_clock = listOf(clock.single().copy(counter = 3)))
        val (rejected, rejectedStatus) = PersonalSync.applyDeletionDecisions(input, listOf(first, badClock))
        assertEquals("conflict", rejectedStatus)
        assertEquals(input, rejected)

        val (applied, appliedStatus) = PersonalSync.applyDeletionDecisions(input, listOf(first, second))
        assertEquals("applied", appliedStatus)
        assertEquals(listOf(first, second), applied.personalSync.applied_decision_proofs)
        assertEquals("resolved", applied.personalSync.entities.getValue("note\u0000a").status)

        assertEquals("applied", PersonalSync.applyDeletionDecisions(applied, listOf(first)).second)
        for (altered in listOf(first.copy(decision = "restore"),
                first.copy(expected_clock = listOf(clock.single().copy(counter = 9))))) {
            val (unchanged, status) = PersonalSync.applyDeletionDecisions(applied, listOf(altered, second))
            assertEquals("conflict", status)
            assertEquals(applied, unchanged)
        }
    }


    @Test fun `decision proofs remain immutable after more than 500 later decisions`() {
        val decisions = (0..501).map { number -> AppliedPersonalDecision(
            "%08x-0000-4000-8000-%012x".format(number, number), "delete", clock,
            "%08x-0001-4000-8000-%012x".format(number, number)) }
        var state = Bestand(personalSync = PersonalSyncState(entities = decisions.associate { decision ->
            "note\u0000${decision.proposal_id}" to PersonalSyncEntity(clock = clock,
                proposal_id = decision.proposal_id, status = "pending")
        }))
        decisions.forEach { decision ->
            val result = PersonalSync.applyDeletionDecisions(state, listOf(decision))
            assertEquals("applied", result.second)
            state = result.first
        }
        assertEquals(502, state.personalSync.applied_decision_proofs.size)

        val firstDecision = decisions.first()
        assertEquals("conflict", PersonalSync.applyDeletionDecisions(state,
            listOf(firstDecision.copy(decision = "restore"))).second)
        assertEquals("conflict", PersonalSync.applyDeletionDecisions(state,
            listOf(decisions[1].copy(decision_id = firstDecision.decision_id))).second)
    }
}
