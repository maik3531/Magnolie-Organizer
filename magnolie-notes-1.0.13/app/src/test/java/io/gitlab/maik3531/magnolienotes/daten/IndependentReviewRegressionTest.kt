package io.gitlab.maik3531.magnolienotes.daten

import io.gitlab.maik3531.magnolienotes.baum.Nutzlast
import io.gitlab.maik3531.magnolienotes.aufgaben.Kalendertage
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate

class IndependentReviewRegressionTest {
    private val peer = "11111111-1111-4111-8111-111111111111"

    @Test fun authenticatedTaskOriginCannotBeForged() {
        val body = buildJsonObject {
            put("art", "aufgabe"); put("id", "task"); put("titel", "Test"); put("herkunft", "other")
        }
        assertNull(Nutzlast.liesAufgabe(body, peer))
        assertEquals(peer, Nutzlast.liesAufgabe(JsonObject(body - "herkunft"), peer)!!.herkunft)
    }

    @Test fun sharingAnExistingNoteIsNotDeletion() {
        val original = Bestand(notizen = listOf(Notiz("n", titel = "Note")))
        val baseline = PersonalSync.acknowledge(PersonalSync.reconcile(original, setOf("notes"), 2).first, peer)
        val shared = baseline.copy(notizen = baseline.notizen.map { it.copy(baumQuelle = "tree") })
        val result = PersonalSync.reconcile(shared, setOf("notes"), 2).first
        assertEquals("live", result.personalSync.entities.getValue("note\u0000n").state)
        assertTrue(PersonalSync.proposals(result, peer).isEmpty())
    }

    @Test fun personalSyncNeverDuplicatesExcludedObjectIds() {
        val original = Bestand(notizen = listOf(Notiz("n", titel = "Note")))
        val remote = PersonalSync.reconcile(original, setOf("notes"), 2).second
        val excluded = original.copy(notizen = original.notizen.map { it.copy(baumQuelle = "tree") })
        val result = PersonalSync.apply(excluded, remote)
        assertEquals(excluded.notizen, result.bestand.notizen)
        assertEquals(1, result.conflicts)
    }

    @Test fun savedEditsRequireDeletionConflictConfirmation() {
        val original = Bestand(notizen = listOf(Notiz("n", titel = "Note")))
        val baseline = PersonalSync.reconcile(original, setOf("notes"), 2).first
        val meta = baseline.personalSync.entities.getValue("note\u0000n")
        val proposal = PersonalDeletionProposal("run", "proposal", "note", "n",
            clock = meta.clock.map { it.copy(counter = it.counter + 1) }, prior_hash = meta.hash, deleted_ms = 1000)
        assertEquals(PersonalDeletionPrompt.NORMAL, PersonalDeletionDecisions().prompt(baseline, proposal))
        val edited = baseline.copy(notizen = listOf(Notiz("n", titel = "Changed")))
        assertEquals(PersonalDeletionPrompt.CONFLICT, PersonalDeletionDecisions().prompt(edited, proposal))
    }

    @Test fun civilDatesIgnoreSpringAndAutumnDst() {
        assertEquals(1, Kalendertage.bis("2026-03-30", LocalDate.parse("2026-03-29")))
        assertEquals(-1, Kalendertage.bis("2026-03-29", LocalDate.parse("2026-03-30")))
        assertEquals(1, Kalendertage.bis("2026-10-26", LocalDate.parse("2026-10-25")))
        assertNull(Kalendertage.bis("2026-02-30"))
    }
}
