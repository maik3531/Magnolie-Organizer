package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PersonalDeletionDecisionsTest {
    private val clock = listOf(PersonalSyncClock("11111111-1111-4111-8111-111111111111", 2))
    private val oldClock = listOf(PersonalSyncClock("11111111-1111-4111-8111-111111111111", 1))
    private val proposal = PersonalDeletionProposal("run-a", "proposal", "note", "n", clock = clock,
        prior_hash = "a".repeat(64), deleted_ms = 1)

    private fun state(meta: PersonalSyncEntity = PersonalSyncEntity(oldClock, "a".repeat(64), state = "live")) =
        Bestand(notizen = listOf(Notiz("n")), personalSync = PersonalSyncState(
            entities = mapOf("note\u0000n" to meta), pending_proposals = listOf(proposal)))

    @Test fun `remember applies only to unchanged proposals in the same run`() {
        val decisions = PersonalDeletionDecisions()
        decisions.remember("run-a", "delete")
        assertEquals(PersonalDeletionPrompt.REMEMBERED, decisions.prompt(state(), proposal))
        assertEquals(PersonalDeletionPrompt.NORMAL, decisions.prompt(state(), proposal.copy(run_id = "run-b")))
        decisions.resolveRun("run-a")
        assertEquals(PersonalDeletionPrompt.NORMAL, decisions.prompt(state(), proposal))
    }

    @Test fun `hash and vector conflicts bypass remembered consent`() {
        val decisions = PersonalDeletionDecisions().apply { remember("run-a", "delete") }
        assertEquals(PersonalDeletionPrompt.CONFLICT, decisions.prompt(state(
            PersonalSyncEntity(oldClock, "b".repeat(64), state = "live")), proposal))
        assertEquals(PersonalDeletionPrompt.CONFLICT, decisions.prompt(state(
            PersonalSyncEntity(clock, "a".repeat(64), state = "live")), proposal))
    }

    @Test fun `mass threshold and nonempty notebook are guarded`() {
        val decisions = PersonalDeletionDecisions()
        assertFalse(decisions.needsMassConfirmation(1, 5))
        assertTrue(decisions.needsMassConfirmation(2, 5))
        assertTrue(decisions.needsMassConfirmation(11, 500))
        val notebook = proposal.copy(kind = "notebook", id = "book")
        val input = Bestand(notizen = listOf(Notiz("n", notizbuchId = "book")))
        assertEquals(PersonalDeletionPrompt.BLOCKED, decisions.prompt(input, notebook))
    }
}
