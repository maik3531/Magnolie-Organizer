package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class ZeitSteuerungTest {
    private val peer = "a".repeat(64)
    private val epoch = "native-book-epoch"
    private val now = 1760000040000L
    private fun initial() = ZeiterfassungStand(enabled = true)
    private fun command(state: ZeiterfassungStand, action: String, entry: String = "") =
        ZeitSteuerBefehl(UUID.randomUUID().toString(), action, ZeitSteuerung.revision(state), entry)
    private fun apply(state: ZeiterfassungStand, value: ZeitSteuerBefehl, at: Long = now) =
        ZeitSteuerung.apply(state, value, peer, epoch, at, "UTC")

    @Test fun lifecycleUsesNativeTimerClocksAndPauseAccounting() {
        val start = command(initial(), "start").copy(activity = "Owned native work", note = "Private timer note")
        val started = apply(initial(), start).state
        val id = started.entries.single().id
        assertEquals(start.operationId, id)
        val paused = apply(started, command(started, "pause", id), now + 120000).state
        val resumed = apply(paused, command(paused, "resume", id), now + 420000).state
        val finished = apply(resumed, command(resumed, "finish", id), now + 600000).state
        assertEquals(5L, finished.entries.single().pauseMinutes)
        assertEquals(5L, finished.entries.single().totalMinutes())
        assertEquals(4L, finished.counter)
        assertEquals(4, finished.controlReceipts.size)
        assertEquals(finished.entries.single().clock, finished.controlReceipts.last().clock)
        assertEquals(finished, Json.decodeFromString<ZeiterfassungStand>(Json.encodeToString(finished)).validate())
    }

    @Test fun retriedOperationKeepsCurrentStateAndReturnsOriginalAppliedClock() {
        val start = command(initial(), "start")
        val first = apply(initial(), start)
        val changed = apply(first.state, command(first.state, "pause", start.operationId), now + 60000)
        val replay = apply(changed.state, start, now + 120000)
        assertTrue(replay.duplicate)
        assertEquals(changed.state, replay.state)
        assertEquals(first.receipt, replay.receipt)
        assertEquals(2L, replay.state.counter)
    }

    @Test fun sourceEpochPeerAndChangedPayloadCannotReuseAnOperation() {
        val start = command(initial(), "start")
        val saved = apply(initial(), start).state
        assertThrows(IllegalStateException::class.java) { apply(saved, start.copy(activity = "Changed command")) }
        assertThrows(IllegalStateException::class.java) { ZeitSteuerung.apply(saved, start, "b".repeat(64), epoch, now, "UTC") }
        assertThrows(IllegalStateException::class.java) { ZeitSteuerung.apply(saved, start, peer, "restored-book-epoch", now, "UTC") }
    }

    @Test fun staleRevisionAndWrongRunningIdentityCannotOverwriteTheTimer() {
        val start = command(initial(), "start")
        val saved = apply(initial(), start).state
        assertThrows(IllegalStateException::class.java) { apply(saved, command(initial(), "pause", start.operationId)) }
        assertThrows(IllegalStateException::class.java) { apply(saved, command(saved, "pause", UUID.randomUUID().toString())) }
        assertEquals(1, saved.controlReceipts.size)
        assertNull(saved.entries.single().pauseMinute)
    }

    @Test fun newStartCannotDuplicateRunningOrReopenCompletedIdentity() {
        val start = command(initial(), "start")
        val saved = apply(initial(), start).state
        assertThrows(IllegalStateException::class.java) { apply(saved, command(saved, "start")) }
        val done = apply(saved, command(saved, "finish", start.operationId), now + 60000).state
        assertTrue(apply(done, start).duplicate)
        val withoutReceipt = done.copy(controlReceipts = emptyList())
        assertThrows(IllegalStateException::class.java) {
            apply(withoutReceipt, start.copy(expectedRevision = ZeitSteuerung.revision(withoutReceipt)))
        }
        assertThrows(IllegalStateException::class.java) { apply(done, command(done, "resume", start.operationId)) }
    }

    @Test fun disabledFeatureAndInvalidCommandDoNotProduceReceipts() {
        val disabled = ZeiterfassungStand()
        assertThrows(IllegalStateException::class.java) { apply(disabled, command(disabled, "start")) }
        assertThrows(IllegalArgumentException::class.java) { apply(initial(), command(initial(), "shell")) }
        assertThrows(IllegalArgumentException::class.java) { apply(initial(), command(initial(), "start").copy(entryId = UUID.randomUUID().toString())) }
        assertTrue(disabled.controlReceipts.isEmpty())
    }

    @Test fun receiptLedgerIsBoundedAndSeparateFromSharedRecordContent() {
        val base = apply(initial(), command(initial(), "start")).state
        val template = base.controlReceipts.single()
        val full = base.copy(controlReceipts = (1..128).map { template.copy(operationId = UUID.randomUUID().toString()) })
        val next = apply(full, command(full, "pause", base.entries.single().id), now + 60000).state
        assertEquals(128, next.controlReceipts.size)
        assertFalse(next.controlReceipts.any { it.operationId == full.controlReceipts.first().operationId })
        assertEquals(base.entries.single().copy(pauseMinute = (now + 60000) / 60000, modifiedMs = next.entries.single().modifiedMs,
            clock = next.entries.single().clock), next.entries.single())
        val shared = io.gitlab.maik3531.magnolienotes.telefon.TimeSyncProtokoll.encodeRecords(next.entries).toString()
        assertFalse(shared.contains("controlReceipts")); assertFalse(shared.contains("requestHash")); assertFalse(shared.contains(peer))
    }
}
