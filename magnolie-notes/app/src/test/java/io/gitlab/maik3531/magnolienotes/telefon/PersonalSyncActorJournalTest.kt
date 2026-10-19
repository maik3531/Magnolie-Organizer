package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
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
    }

    @Test fun sourceAndLeaseRacesRollbackDatabaseWorkAndAllowNativeRetirement() = fixture { db, storage ->
        var source: String? = REV; var restore = "book-epoch"; var wall = 1000L; var elapsed = 100L
        val journal = PersonalSyncActorJournal(db, storage, { _, _ -> source }, { restore },
            clock = { wall }, monotonic = { elapsed })
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
        active.forEach(journal::retire)
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
