package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.security.Provider
import java.security.Security

/** Real SQLite and production payload encryption, synthetic Keystore only. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PersonalSyncActorJournalTest {
    @Test fun historicalWriterGateRequiresRealVolatileDataRetirementAndCannotBeReopenedFromSealedPhaseAlone() = fixture { db, storage ->
        val epoch = "e".repeat(64)
        fun journal() = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" }, ownerEpoch = epoch)
        val owner = journal(); val handle = owner.create(PEER, KEY, REV)
        assertTrue(runCatching { owner.checkHistoricalSave(handle) }.isFailure)
        owner.withActive(handle) {}
        owner.beginCompletion(handle) { _, _ -> true }
        assertTrue(runCatching { owner.withActive(handle) {} }.isFailure)
        owner.checkHistoricalSave(handle)
        assertTrue(runCatching { journal().checkHistoricalSave(handle) }.isFailure)
        owner.finishCompletion(handle)
        assertTrue(runCatching { owner.checkHistoricalSave(handle) }.isFailure)
        assertEquals("completed", owner.completionState(handle))
    }

    @Test fun sealedOwnershipSurvivesReopenButNotNativeEpochReplacement() = fixture { db, storage ->
        val epoch = "e".repeat(64)
        fun journal() = PersonalSyncActorJournal(db, storage, { peer, key ->
            if (peer == PEER && key == KEY) REV else null
        }, { "book-epoch" }, ownerEpoch = epoch)
        val handle = journal().create(PEER, KEY, REV)
        assertFalse(handle.toString().contains(handle.token))
        assertEquals(7, journal().withActive(handle) { 7 })
        db.readableDatabase.query("meta", arrayOf("value"), "key GLOB ?", arrayOf("personal_actor_journal:*"), null, null, null).use {
            assertTrue(it.moveToFirst())
            assertFalse(it.getBlob(0).decodeToString().contains(REV))
            assertFalse(it.getBlob(0).decodeToString().contains(handle.token))
        }
        db.close()
        assertEquals(9, journal().withActive(handle) { 9 })
        assertTrue(runCatching { journal().withActive(PersonalActorHandle(PEER, handle.runId, "0".repeat(64))) { 0 } }.isFailure)
        val replacement = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" })
        assertTrue(runCatching { replacement.withActive(handle) { 0 } }.isFailure)
        assertTrue(runCatching { replacement.retire(handle) }.isFailure)
        journal().retire(handle)
        assertTrue(journal().stopped(handle))
        assertTrue(runCatching { journal().withActive(handle) { 0 } }.isFailure)
        assertTrue(runCatching { journal().create(PEER, KEY, REV, handle.runId) }.isFailure)
        // Native books without tree sync legitimately start with an empty syncEpoch.
        val initialBook = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "" })
        val initial = initialBook.create(PEER, KEY, REV)
        assertEquals(11, initialBook.withActive(initial) { 11 })
    }

    @Test fun sourceAndLeaseRacesRollbackDatabaseWorkAndAllowNativeRetirement() = fixture { db, storage ->
        var source: String? = REV; var restore = "book-epoch"; var wall = 1000L; var elapsed = 100L
        val sourceLock = Any(); val bookLock = Any()
        val journal = PersonalSyncActorJournal(db, storage, { _, _ ->
            check(Thread.holdsLock(sourceLock) && Thread.holdsLock(bookLock)); source
        }, { restore }, clock = { wall }, monotonic = { elapsed }, sourceLock = sourceLock, bookLock = bookLock)
        val handle = journal.create(PEER, KEY, REV)
        assertTrue(runCatching { journal.withActive(handle) {
            execSQL("INSERT INTO meta(key,value) VALUES('actor-fixture',X'01')")
            source = null
        } }.isFailure)
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM meta WHERE key='actor-fixture'", null).use {
            assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
        }
        source = REV; restore = "another-book"
        assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
        restore = "book-epoch"; elapsed += 30 * 60 * 1000
        assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
        elapsed = 100; wall = 999
        assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
        source = null
        journal.retire(handle); journal.retire(handle)
        assertTrue(journal.stopped(handle))
        assertTrue(runCatching { journal.create(PEER, KEY, REV) }.isFailure)
    }

    @Test fun retainedAndActiveCapacityAreBoundedAndCiphertextTamperingFailsClosed() = fixture { db, storage ->
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" })
        val active = (1..4).map { journal.create(PEER, KEY, REV) }
        assertTrue(runCatching { journal.create(PEER, KEY, REV) }.isFailure)
        active.forEach { journal.retire(it) }
        repeat(28) { journal.retire(journal.create(PEER, KEY, REV)) }
        assertTrue(runCatching { journal.create(PEER, KEY, REV) }.isFailure)
        val handle = active.first()
        db.writableDatabase.execSQL("UPDATE meta SET value=X'00' WHERE key=?",
            arrayOf("personal_actor_journal:${handle.peerId}:${handle.runId}"))
        assertTrue(runCatching { journal.stopped(handle) }.isFailure)
        assertTrue(runCatching { journal.retire(handle) }.isFailure)
    }

    @Test fun sourceChangeDuringCreationCannotLeaveAnAdmittedJournal() = fixture { db, storage ->
        var checks = 0
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> if (++checks == 1) REV else null }, { "book-epoch" })
        assertTrue(runCatching { journal.create(PEER, KEY, REV) }.isFailure)
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM meta WHERE key GLOB 'personal_actor_journal:*'", null).use {
            assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
        }
    }

    @Test fun rawActorWireDeduplicatesWithoutLosingItsMarkerOrGrantingLegacyAdmission() = fixture { db, storage ->
        var now = System.currentTimeMillis()
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" }, clock = { now })
        val handle = journal.create(PEER, KEY, REV)
        val request = buildJsonObject {
            put("format", 3); put("run_id", handle.runId); put("trigger", "manual")
            put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks"))))
        }
        val ordinary = TelefonNachrichten.message("personal_sync.request", request, 60000, now)
        val wire = PersonalSyncActor.wireMessage(ordinary, handle.runId)
        assertTrue(journal.putWire(handle, wire)); assertFalse(journal.putWire(handle, wire))
        db.close()
        assertEquals(wire, journal.readWire(handle, wire.string("message_id")))
        assertTrue(runCatching { journal.putWire(handle, ordinary) }.isFailure)
        val changed = JsonObject(wire + ("expires_ms" to JsonPrimitive(now + 59000)))
        assertTrue(runCatching { journal.putWire(handle, changed) }.isFailure)
        val other = journal.create(PEER, KEY, REV)
        assertTrue(runCatching { journal.putWire(other, wire) }.isFailure)
        val ack = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(handle.runId, ordinary.string("message_id")), 60000, now)
        assertTrue(journal.putWire(handle, ack))
        now += 60001
        assertEquals(ack, journal.readWire(handle, ack.string("message_id")))
        assertTrue(runCatching { journal.putWire(handle, ack) }.isFailure)
        journal.retire(handle)
        assertTrue(runCatching { journal.readWire(handle, wire.string("message_id")) }.isFailure)
    }

    @Test fun rawWirePostcheckRevocationRollsBackAndCiphertextIdentityCannotBeMoved() = fixture { db, storage ->
        var checks = 0; var revokeAt = Int.MAX_VALUE
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> if (++checks >= revokeAt) null else REV }, { "book-epoch" })
        val handle = journal.create(PEER, KEY, REV)
        val wire = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(handle.runId, "33333333-3333-4333-8333-333333333333"), 60000)
        revokeAt = checks + 2
        assertTrue(runCatching { journal.putWire(handle, wire) }.isFailure)
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM meta WHERE key GLOB 'personal_actor_wire:*'", null).use {
            assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
        }
        revokeAt = Int.MAX_VALUE
        assertTrue(journal.putWire(handle, wire))
        val originalKey = "personal_actor_wire:${handle.peerId}:${handle.runId}:${wire.string("message_id")}"
        val otherId = "44444444-4444-4444-8444-444444444444"
        db.writableDatabase.execSQL("UPDATE meta SET key=? WHERE key=?",
            arrayOf("personal_actor_wire:${handle.peerId}:${handle.runId}:$otherId", originalKey))
        assertTrue(runCatching { journal.readWire(handle, otherId) }.isFailure)
    }

    @Test fun nativeRestartAndExpiryCleanupRetainLiveOwnersAndRollbackFailedRetirement() = fixture { db, storage ->
        var wall = 1000L; var elapsed = 100L
        fun journal(epoch: String) = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" },
            ownerEpoch = epoch.repeat(64), clock = { wall }, monotonic = { elapsed })
        val previous = journal("a")
        val old = previous.create(PEER, KEY, REV)
        val ack = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(old.runId, "33333333-3333-4333-8333-333333333333"), 60000, wall)
        assertTrue(previous.putWire(old, ack))
        val current = journal("b")
        val live = current.create(PEER, KEY, REV)
        db.writableDatabase.execSQL("INSERT INTO meta(key,value) VALUES('ordinary-fixture',X'01')")
        assertEquals(listOf(PEER to old.runId), current.reapInactive { peer, run ->
            assertEquals(PEER, peer); assertEquals(old.runId, run)
        })
        assertEquals(8, current.withActive(live) { 8 })
        assertTrue(runCatching { previous.stopped(old) }.isFailure)
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM meta WHERE key GLOB 'personal_actor_wire:*'", null).use {
            assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
        }
        wall += 30 * 60 * 1000; elapsed += 30 * 60 * 1000
        assertTrue(runCatching { current.reapInactive { _, _ ->
            execSQL("DELETE FROM meta WHERE key='ordinary-fixture'")
            error("Synthetic retirement failure")
        } }.isFailure)
        assertFalse(current.stopped(live))
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM meta WHERE key='ordinary-fixture'", null).use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        assertEquals(listOf(PEER to live.runId), current.reapInactive { _, _ -> })
        assertTrue(runCatching { current.stopped(live) }.isFailure)
        assertTrue(current.reapInactive { _, _ -> error("No work should remain") }.isEmpty())
    }

    @Test fun nativeCompletionClosesDataAndRetainsOnlySealedControlMetadata() = fixture { db, storage ->
        var source: String? = REV; var now = System.currentTimeMillis(); var saved = false
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> source }, { "book-epoch" }, clock = { now })
        val handle = journal.create(PEER, KEY, REV)
        val request = buildJsonObject { put("format", 3); put("run_id", handle.runId); put("trigger", "manual")
            put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks")))) }
        val data = PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.request", request, 60000, now), handle.runId)
        journal.putWire(handle, data)
        assertTrue(runCatching { journal.readCompletionControls(handle) }.isFailure)
        val guard: (String, JsonObject?) -> Boolean? = { op, _ -> if (op == "finish" && !saved) null else true }
        assertEquals("completion", journal.beginCompletion(handle, guard)); journal.beginCompletion(handle, guard)
        assertTrue(runCatching { journal.readWire(handle, data.string("message_id")) }.isFailure)
        assertTrue(runCatching { journal.putWire(handle, data) }.isFailure)
        assertTrue(runCatching { journal.putCompletionControl(handle, data) }.isFailure)
        source = "b".repeat(64)
        val control = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(handle.runId, "33333333-3333-4333-8333-333333333333"), 60000, now)
        assertTrue(journal.putCompletionControl(handle, control)); assertFalse(journal.putCompletionControl(handle, control))
        assertEquals(listOf(control), journal.readCompletionControls(handle))
        db.readableDatabase.query("meta", arrayOf("value"), "key GLOB ?", arrayOf("personal_actor_completion_wire:*"), null, null, null).use {
            assertTrue(it.moveToFirst()); assertFalse(it.getBlob(0).decodeToString().contains(control.string("message_id")))
        }
        now += 60001
        assertEquals(listOf(control), journal.readCompletionControls(handle))
        assertTrue(runCatching { journal.putCompletionControl(handle, control) }.isFailure)
        assertTrue(runCatching { journal.finishCompletion(handle) }.isFailure)
        saved = true
        assertEquals("completed", journal.finishCompletion(handle)); assertEquals("completed", journal.finishCompletion(handle))
        assertTrue(runCatching { journal.withActive(handle) { 1 } }.isFailure)
    }

    @Test fun completionWaitsForFreshEvidenceAndBadControlsCannotStealItsOwner() = fixture { db, storage ->
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" })
        val handle = journal.create(PEER, KEY, REV); var ready = true; var lost = false
        val expected = "33333333-3333-4333-8333-333333333333"
        val guard: (String, JsonObject?) -> Boolean? = { op, wire ->
            if (lost) false else if (!ready) null else {
                if (op == "put") require(wire!!.getValue("body").jsonObject.string("message_id") == expected)
                true
            }
        }
        journal.beginCompletion(handle, guard)
        val control = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND, PersonalSyncActor.ack(handle.runId, expected), 60000)
        ready = false
        assertTrue(runCatching { journal.putCompletionControl(handle, control) }.isFailure)
        assertEquals("completion", journal.completionState(handle)); ready = true
        val unexpected = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(handle.runId, "44444444-4444-4444-8444-444444444444"), 60000)
        assertTrue(runCatching { journal.putCompletionControl(handle, unexpected) }.isFailure)
        val wrong = PersonalActorHandle(PEER, handle.runId, "0".repeat(64))
        assertTrue(runCatching { journal.retire(wrong) }.isFailure)
        assertTrue(runCatching { journal.readCompletionControls(wrong) }.isFailure)
        assertTrue(runCatching { journal.beginCompletion(handle) { _, _ -> true } }.isFailure)
        assertTrue(journal.putCompletionControl(handle, control))
        lost = true; assertTrue(runCatching { journal.readCompletionControls(handle) }.isFailure)
        assertEquals("cancelled", journal.completionState(handle)); lost = false
        assertTrue(runCatching { journal.readCompletionControls(handle) }.isFailure)
    }

    @Test fun completionPostcheckRollsBackAndHistoricalBindingCannotReviveData() = fixture { db, storage ->
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" })
        val handle = journal.create(PEER, KEY, REV)
        val id = "personal_actor_journal:$PEER:${handle.runId}"
        val original = db.readableDatabase.query("meta", arrayOf("value"), "key=?", arrayOf(id), null, null, null).use { check(it.moveToFirst()); it.getBlob(0) }
        var puts = 0
        val guard: (String, JsonObject?) -> Boolean? = { op, _ -> op != "put" || ++puts != 2 }
        journal.beginCompletion(handle, guard)
        val control = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(handle.runId, "33333333-3333-4333-8333-333333333333"), 60000)
        assertTrue(runCatching { journal.putCompletionControl(handle, control) }.isFailure)
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM meta WHERE key GLOB 'personal_actor_completion_wire:*'", null).use {
            assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
        }
        db.writableDatabase.execSQL("UPDATE meta SET value=? WHERE key=?", arrayOf(original, id))
        assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
    }

    @Test fun completionLeaseRestoreAndRegistryReplacementCannotInheritAuthority() = fixture { db, storage ->
        var wall = System.currentTimeMillis(); var mono = 1000L; var restore = "book-epoch"
        fun journal() = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { restore }, ownerEpoch = "e".repeat(64), clock = { wall }, monotonic = { mono })
        val current = journal(); val guard: (String, JsonObject?) -> Boolean? = { _, _ -> true }
        for (mode in listOf("wall-expiry", "mono-expiry", "wall-rollback", "mono-rollback", "restore")) {
            val handle = current.create(PEER, KEY, REV); current.beginCompletion(handle, guard)
            val beforeWall = wall; val beforeMono = mono
            when (mode) {
                "wall-expiry" -> wall += 30 * 60 * 1000 + 1
                "mono-expiry" -> mono += 30 * 60 * 1000 + 1
                "wall-rollback" -> wall--
                "mono-rollback" -> mono--
                "restore" -> restore = "changed-book"
            }
            assertTrue(mode, runCatching { current.readCompletionControls(handle) }.isFailure)
            wall = beforeWall; mono = beforeMono; restore = "book-epoch"
        }
        val handle = current.create(PEER, KEY, REV); current.beginCompletion(handle, guard)
        assertTrue(runCatching { journal().readCompletionControls(handle) }.isFailure)
        assertTrue(runCatching { current.readCompletionControls(handle) }.isFailure)
    }

    @Test fun completionOwnerStillCountsTowardActiveCapacity() = fixture { db, storage ->
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" })
        val handle = journal.create(PEER, KEY, REV); journal.beginCompletion(handle) { _, _ -> true }
        repeat(3) { journal.create(PEER, KEY, REV) }
        assertTrue(runCatching { journal.create(PEER, KEY, REV) }.isFailure)
        journal.retire(handle); journal.create(PEER, KEY, REV)
    }

    @Test fun savedActorIntentSetCommitsAtomicallyAndExactReplayStaysProcessed() = fixture { db, storage ->
        val context = ApplicationProvider.getApplicationContext<Context>()
        val queue = TelefonQueue(context, storage)
        try {
            val run = "44444444-4444-4444-8444-444444444444"
            val messages = (0..1).map { index -> TelefonNachrichten.message("personal_sync.deletion_proposals", buildJsonObject {
                put("format", 1); put("run_id", run); put("proposal_batch_id", java.util.UUID.randomUUID().toString())
                put("sequence", index); put("last", index == 1); put("proposals", JsonArray(emptyList()))
            }, 60000) }
            messages.forEach { queue.stageActorDeletionIntent(run, it) }
            assertFalse(queue.commitActorDeletionIntents(run, messages.take(1)))
            val changed = messages.mapIndexed { index, value -> if (index == 1) JsonObject(value + ("expires_ms" to JsonPrimitive(value.long("expires_ms") - 1))) else value }
            assertFalse(queue.commitActorDeletionIntents(run, changed))
            assertEquals(2, queue.actorDeletionIntents(run).size)
            val second = messages[1].string("message_id")
            db.writableDatabase.execSQL("CREATE TRIGGER actor_intent_failure BEFORE UPDATE ON inbox WHEN OLD.message_id='$second' AND NEW.state='actor_processed' BEGIN SELECT RAISE(ABORT,'synthetic native failure'); END")
            assertTrue(runCatching { queue.commitActorDeletionIntents(run, messages) }.isFailure)
            assertEquals(2, queue.actorDeletionIntents(run).size)
            db.writableDatabase.execSQL("DROP TRIGGER actor_intent_failure")
            assertTrue(queue.commitActorDeletionIntents(run, messages.reversed()))
            assertTrue(queue.actorDeletionIntents(run).isEmpty())
            assertTrue(queue.commitActorDeletionIntents(run, messages))
        } finally {
            (TelefonQueue::class.java.getDeclaredField("helper").apply { isAccessible = true }.get(queue) as TelefonDatenbank).close()
        }
    }

    @Test fun decisionCompletionNeedsFreshScopeAndActualEncryptedAckPersistence() = fixture { db, storage ->
        val f = completionFixture(db, storage)
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, f.ack) }.isFailure)
        assertTrue(runCatching { f.journal.finishCompletion(f.handle) }.isFailure)
        f.scope = f.after
        assertTrue(runCatching { f.guard.recordPersisted(f.ack) }.isFailure)
        assertTrue(f.journal.putCompletionControl(f.handle, f.ack))
        db.close() // Read the actual encrypted SQLite row again, not an acceptance flag.
        f.guard.recordPersisted(f.ack)
        assertEquals(JsonPrimitive(1), f.guard.summary()["saved"])
        assertEquals("completed", f.journal.finishCompletion(f.handle))
        assertTrue(runCatching { f.journal.withActive(f.handle) { 0 } }.isFailure)
    }

    @Test fun completionSendAllowsOnlyExactQueuedDecisionWithoutReopeningData() = fixture { db, storage ->
        val f = completionFixture(db, storage)
        f.journal.checkCompletionSend(f.handle, f.wire)
        val changed = JsonObject(f.wire + ("message_id" to JsonPrimitive(java.util.UUID.randomUUID().toString())))
        assertTrue(runCatching { f.journal.checkCompletionSend(f.handle, changed) }.isFailure)
        assertTrue(runCatching { f.journal.checkCompletionSend(f.handle, f.ack) }.isFailure)
        assertTrue(runCatching { f.journal.withActive(f.handle) { 0 } }.isFailure)
        f.journal.checkCompletionSend(f.handle, f.wire)
    }

    @Test fun completionRejectsUnrelatedBookAuthorityAndMembershipChanges() = fixture { db, storage ->
        for (mode in listOf("book", "authority", "scope")) {
            val f = completionFixture(db, storage)
            when (mode) {
                "book" -> f.saved = JsonObject(f.saved!! + ("sha256" to JsonPrimitive("b".repeat(64))))
                "authority" -> f.authority = "b".repeat(64)
                "scope" -> f.scope = PhoneContentScope.create(setOf("foreign"), setOf("t"))
            }
            assertTrue(mode, runCatching { f.journal.putCompletionControl(f.handle, f.ack) }.isFailure)
            assertEquals(JsonPrimitive(0), f.guard.summary()["saved"])
            assertTrue(runCatching { f.journal.withActive(f.handle) { 0 } }.isFailure)
        }
    }

    @Test fun incompleteScopeWaitsAndExactRestoreStillNeedsPersistedReceipt() = fixture { db, storage ->
        val f = completionFixture(db, storage, restore = true)
        f.scope = null
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, f.ack) }.isFailure)
        f.scope = f.before
        val unrelated = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(f.handle.runId, java.util.UUID.randomUUID().toString()), 60000)
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, unrelated) }.isFailure)
        assertTrue(f.journal.putCompletionControl(f.handle, f.ack))
        f.guard.recordPersisted(f.ack)
        assertFalse(f.journal.putCompletionControl(f.handle, f.ack))
        f.guard.recordPersisted(f.ack)
        assertEquals("completed", f.journal.finishCompletion(f.handle))
    }

    @Test fun failedMetadataWriteAndTemporaryRejectionNeverCountAsSaved() = fixture { db, storage ->
        val f = completionFixture(db, storage)
        f.scope = f.after
        db.writableDatabase.execSQL("CREATE TRIGGER completion_write_failure BEFORE INSERT ON meta WHEN NEW.key GLOB 'personal_actor_completion_wire:*' BEGIN SELECT RAISE(ABORT,'synthetic write failure'); END")
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, f.ack) }.isFailure)
        assertTrue(runCatching { f.guard.recordPersisted(f.ack) }.isFailure)
        db.writableDatabase.execSQL("DROP TRIGGER completion_write_failure")
        val rejected = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(f.handle.runId, f.wire.string("message_id"), "rejected", "temporary_failure"), 60000)
        assertTrue(f.journal.putCompletionControl(f.handle, rejected))
        f.guard.recordPersisted(rejected)
        assertEquals(JsonPrimitive(0), f.guard.summary()["saved"])
        assertTrue(runCatching { f.journal.finishCompletion(f.handle) }.isFailure)
        assertTrue(f.journal.putCompletionControl(f.handle, f.ack))
        f.guard.recordPersisted(f.ack)
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, rejected) }.isFailure)
        assertEquals("completed", f.journal.finishCompletion(f.handle))
    }

    @Test fun nativeIncomingDecisionAckCannotCountBeforeSendAndEncryptedPersistence() = fixture { db, storage ->
        val f = completionFixture(db, storage, nativeAck = true)
        assertTrue(runCatching { f.journal.checkCompletionSend(f.handle, f.wire) }.isFailure)
        assertTrue(runCatching { f.journal.checkCompletionSend(f.handle, f.ack) }.isFailure)
        assertTrue(runCatching { f.guard.recordSuccessfulAcknowledgmentSend(f.ack) }.isFailure)
        f.scope = f.after
        f.journal.checkCompletionSend(f.handle, f.ack)
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, f.ack) }.isFailure)
        assertTrue(runCatching { f.guard.recordPersisted(f.ack) }.isFailure)
        val substituted = JsonObject(f.ack + ("message_id" to JsonPrimitive(java.util.UUID.randomUUID().toString())))
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, substituted) }.isFailure)
        f.guard.recordSuccessfulAcknowledgmentSend(f.ack)
        assertTrue(runCatching { f.guard.recordPersisted(f.ack) }.isFailure)
        assertTrue(f.journal.putCompletionControl(f.handle, f.ack))
        f.guard.recordPersisted(f.ack)
        assertEquals("completed", f.journal.finishCompletion(f.handle))
        assertTrue(runCatching { f.journal.withActive(f.handle) { 0 } }.isFailure)
    }

    @Test fun nativeSentAckStillRequiresTheSameWriterAndAtomicControlWrite() = fixture { db, storage ->
        val f = completionFixture(db, storage, restore = true, nativeAck = true)
        f.journal.checkCompletionSend(f.handle, f.ack)
        f.guard.recordSuccessfulAcknowledgmentSend(f.ack)
        db.writableDatabase.execSQL("CREATE TRIGGER sent_ack_write_failure BEFORE INSERT ON meta WHEN NEW.key GLOB 'personal_actor_completion_wire:*' BEGIN SELECT RAISE(ABORT,'synthetic sent ACK metadata failure'); END")
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, f.ack) }.isFailure)
        assertTrue(runCatching { f.guard.recordPersisted(f.ack) }.isFailure)
        assertEquals(JsonPrimitive(0), f.guard.summary()["saved"])
        db.writableDatabase.execSQL("DROP TRIGGER sent_ack_write_failure")
        f.saved = JsonObject(f.saved!! + ("sequence" to JsonPrimitive(2)))
        assertTrue(runCatching { f.journal.putCompletionControl(f.handle, f.ack) }.isFailure)
        assertTrue(runCatching { f.journal.finishCompletion(f.handle) }.isFailure)
        assertTrue(runCatching { f.journal.withActive(f.handle) { 0 } }.isFailure)
    }

    private class CompletionFixture(val journal: PersonalSyncActorJournal, val handle: PersonalActorHandle,
        val before: JsonObject, val after: JsonObject, val wire: JsonObject) {
        var scope: JsonObject? = before
        var authority: String? = REV
        var saved: JsonObject? = buildJsonObject { put("book_source", REV); put("sequence", 1); put("sha256", REV) }
        lateinit var guard: PersonalActorDecisionCompletion
        val ack = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
            PersonalSyncActor.ack(handle.runId, wire.string("message_id")), 60000)
    }

    private fun completionFixture(db: TelefonDatenbank, storage: TelefonAblage, restore: Boolean = false,
        nativeAck: Boolean = false): CompletionFixture {
        val cases = Json.parseToJsonElement(requireNotNull(javaClass.getResource("/notes-actor-completion-scope.json")).readText())
            .jsonObject.getValue("cases").jsonArray
        val vector = cases.first { it.jsonObject.string("name") == "delete-note" }.jsonObject
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> REV }, { "book-epoch" })
        val handle = journal.create(PEER, KEY, REV)
        val decisions = if (!restore) vector.getValue("decisions").jsonArray else JsonArray(
            vector.getValue("decisions").jsonArray.map { JsonObject(it.jsonObject + ("decision" to JsonPrimitive("restore"))) })
        val body = buildJsonObject {
            put("format", 1); put("run_id", handle.runId); put("decision_id", java.util.UUID.randomUUID().toString()); put("decisions", decisions)
        }
        val wire = PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.deletion_decision", body, 60000), handle.runId)
        val f = CompletionFixture(journal, handle, vector.getValue("before").jsonObject,
            vector.getValue(if (restore) "before" else "actual_after").jsonObject, wire)
        f.guard = PersonalActorDecisionCompletion(handle.runId, vector.getValue("native_targets").jsonArray, listOf(wire),
            { f.authority }, { f.scope }, { f.saved }, { journal.readCompletionControls(handle) },
            nativeSentAcknowledgments = if (nativeAck) listOf(f.ack) else emptyList())
        journal.beginCompletion(handle, f.guard.validator)
        return f
    }

    private fun fixture(test: (TelefonDatenbank, TelefonAblage) -> Unit) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("ActorJournalFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        val singleton = TelefonAblage::class.java.getDeclaredField("instance").apply { isAccessible = true }
        val prior = singleton.get(null); singleton.set(null, null)
        context.deleteDatabase("magnolie_phone.db")
        val db = TelefonDatenbank(context)
        try { test(db, TelefonAblage.get(context)) } finally {
            db.close(); context.deleteDatabase("magnolie_phone.db")
            singleton.set(null, prior); Security.removeProvider(provider.name)
        }
    }

    companion object {
        private const val PEER = "22222222-2222-4222-8222-222222222222"
        private val KEY = TelefonKrypto.b64(ByteArray(32) { 7 })
        private val REV = "a".repeat(64)
    }
}
