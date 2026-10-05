package io.gitlab.maik3531.magnolienotes.daten

import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class ZeiterfassungAbgleichTest {
    private fun original() = ZeiterfassungStand(enabled = true).replace(null,
        Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC", note = "Initial"))

    @Test fun newerRecordsApplyAndOlderOrRepeatedDeliveryCannotUndoEdits() {
        val first = original()
        val base = first.entries.single()
        val newer = base.copy(note = "Newer", clock = base.clock + (UUID.randomUUID().toString() to 1L))
        val applied = ZeiterfassungAbgleich.merge(first, listOf(newer)).state
        assertEquals("Newer", applied.entries.single().note)
        assertEquals(applied, ZeiterfassungAbgleich.merge(applied, listOf(newer)).state)
        assertEquals(applied, ZeiterfassungAbgleich.merge(applied, listOf(base)).state)
    }

    @Test fun concurrentVersionsRemainReviewableAndResolutionDominatesBoth() {
        val first = original()
        val base = first.entries.single()
        val local = first.replace(base, base.copy(note = "Local"))
        val remote = base.copy(note = "Remote", clock = base.clock + (UUID.randomUUID().toString() to 1L))
        val conflicted = ZeiterfassungAbgleich.merge(local, listOf(remote)).state
        assertEquals("Local", conflicted.entries.single().note)
        assertEquals(listOf(remote), conflicted.conflicts.getValue(base.id))
        assertEquals(conflicted, ZeiterfassungAbgleich.merge(conflicted, listOf(remote)).state)
        val resolved = ZeiterfassungAbgleich.resolve(conflicted, base.id, remote, listOf(remote), local.entries.single())
        assertEquals("Remote", resolved.entries.single().note)
        assertTrue(resolved.conflicts.isEmpty())
        assertTrue(ZeiterfassungAbgleich.dominates(resolved.entries.single().clock, local.entries.single().clock))
        assertTrue(ZeiterfassungAbgleich.dominates(resolved.entries.single().clock, remote.clock))
        assertEquals(resolved, ZeiterfassungAbgleich.merge(resolved, listOf(remote)).state)
    }

    @Test fun equalClocksWithDifferentContentsAreNeverSilentlyOverwritten() {
        val state = original()
        val alternative = state.entries.single().copy(note = "Conflicting actor history")
        val result = ZeiterfassungAbgleich.merge(state, listOf(alternative))
        assertEquals("conflict", result.outcomes[alternative.id])
        assertEquals(state.entries, result.state.entries)
    }

    @Test fun reviewCannotOverwriteLocalEditsOrNewAlternativesArrivingWhileOpen() {
        val initial = original()
        val local = initial.entries.single()
        val remote = local.copy(note = "Remote alternative")
        val conflicted = ZeiterfassungAbgleich.merge(initial, listOf(remote)).state
        val edited = conflicted.replace(local, local.copy(note = "Edited during review"))
        assertThrows(IllegalStateException::class.java) {
            ZeiterfassungAbgleich.resolve(edited, local.id, remote, listOf(remote), local)
        }
        val changed = conflicted.copy(conflicts = mapOf(local.id to listOf(remote, remote.copy(note = "Third version"))))
        assertThrows(IllegalStateException::class.java) {
            ZeiterfassungAbgleich.resolve(changed, local.id, remote, listOf(remote), local)
        }
        val resolved = ZeiterfassungAbgleich.resolve(conflicted, local.id, remote, listOf(remote), local)
        assertThrows(IllegalStateException::class.java) {
            ZeiterfassungAbgleich.resolve(resolved, local.id, remote, listOf(remote), local)
        }
    }

    @Test fun choosingFinishedConflictStopsTrackingAndArmsTheWifiBlockOnlyOnce() {
        val initial = ZeiterfassungStand(enabled = true).start(Zeiteintrag(startMinute = 1000, zone = "UTC"))
        val local = initial.entries.single()
        val remote = local.copy(endMinute = 1060, note = "Stopped on Organizer")
        val conflicted = ZeiterfassungAbgleich.merge(initial, listOf(remote), fromOrganizer = true).state
        val resolved = ZeiterfassungAbgleich.resolve(conflicted, local.id, remote, listOf(remote), local, 1060 * 60000L)
        assertEquals(1060L, resolved.entries.single().endMinute)
        assertTrue(resolved.pauseRuns.isEmpty())
        assertTrue(resolved.wifi.blockedUntilMs > 1060 * 60000L)
        assertEquals(resolved.wifi, ZeiterfassungAbgleich.merge(resolved, listOf(remote),
            fromOrganizer = true, nowMs = 1070 * 60000L).state.wifi)
    }

    @Test fun localRemovedMonthCannotBeReimportedAndNeverEmitsADeletion() {
        val first = original()
        val base = first.entries.single()
        val removed = first.removeLocal(listOf(base), month = "1970-01")
        val unseen = base.copy(id = UUID.randomUUID().toString(), note = "Another Organizer record")
        val merged = ZeiterfassungAbgleich.merge(removed, listOf(base, unseen))
        assertTrue(merged.state.entries.isEmpty())
        assertEquals(setOf("locally_removed"), merged.outcomes.values.toSet())
        assertEquals(removed.trash, merged.state.trash)
    }

    @Test fun emptyReceiverGetsItsOwnActorInsteadOfCopyingTheSendersIdentity() {
        val sender = original()
        val received = ZeiterfassungAbgleich.merge(ZeiterfassungStand(), sender.entries).state
        assertNotEquals(sender.actor, received.actor)
        assertTrue(received.actor.isNotEmpty())
        assertEquals(sender.entries, received.entries)
        assertEquals(0L, received.counter)
    }
}
