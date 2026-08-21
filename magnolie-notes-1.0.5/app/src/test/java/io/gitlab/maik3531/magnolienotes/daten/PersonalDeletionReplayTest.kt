package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertEquals
import org.junit.Test

class PersonalDeletionReplayTest {
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
