package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.nio.file.Files
import java.util.UUID
import javax.crypto.spec.SecretKeySpec
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Writer contract only; native service/journal retirement must be tested separately. */
@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class PersonalHistoricalRestoreWriterTest {
    @Test fun aCollidingTrashIdCannotRemoveAnUnrelatedEncryptedTrashEntryThroughAHistoricalClaim() {
        val directory = Files.createTempDirectory("notes-historical-trash-collision-").toFile()
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        val peer = "22222222-2222-4222-8222-222222222222"; val run = UUID.randomUUID().toString()
        val key = SecretKeySpec(ByteArray(32) { 19 }, "AES")
        try {
            val storage = Ablage.fuerTest(context) { key }
            storage.setzeNotiz(Notiz("restore-note", text = "Synthetic protected source"))
            storage.personalSyncSnapshot(setOf("notes"), 3); storage.personalSyncAcknowledge(peer)
            storage.loescheNotiz("restore-note"); storage.personalSyncSnapshot(setOf("notes"), 3)
            val source = storage.bestand.value.papierkorb.single()
            val collision = source.copy(art = "task", notiz = null, aufgabe = Aufgabe("unrelated-trash", titel = "Keep this trash"))
            val seeded = storage.bestand.value.copy(papierkorb = listOf(source, collision))
            synchronized(Ablage.SCHREIBSPERRE) {
                Ablage::class.java.getDeclaredMethod("schreibeBestand", Bestand::class.java).apply { isAccessible = true }.invoke(storage, seeded)
            }
            val before = storage.bestand.value; val saved = requireNotNull(storage.personalActorSavedBookState())
            val bytes = File(directory, "notizen.json").readBytes()
            val meta = before.personalSync.entities.getValue("note\u0000restore-note")
            val proposal = PersonalDeletionProposal(run, UUID.randomUUID().toString(), "note", "restore-note", "", meta.clock,
                meta.prior_hash, meta.deleted_ms, "Synthetic", peer)
            val decision = AppliedPersonalDecision(proposal.proposal_id, "restore", meta.clock, UUID.randomUUID().toString())
            assertTrue(runCatching { PersonalHistoricalRestoreClaim.prepare(peer, run, before, saved, PersonalSync.livePersonalContent(before),
                listOf(proposal), listOf(decision)) }.isFailure)
            assertSame(before, storage.bestand.value); assertEquals(saved, storage.personalActorSavedBookState())
            assertArrayEquals(bytes, File(directory, "notizen.json").readBytes()); assertNull(storage.notiz("restore-note"))
            val reopened = Ablage.fuerTest(context) { key }
            assertEquals(listOf(source, collision), reopened.bestand.value.papierkorb)
            assertEquals("Keep this trash", reopened.bestand.value.papierkorb.single { it.art == "task" }.aufgabe?.titel)
        } finally { directory.deleteRecursively() }
    }

    @Test fun theDedicatedWriterNeedsItsClosedNativeClaimAndExactlyItsBeforeBookAndSaveWitness() {
        val directory = Files.createTempDirectory("notes-historical-restore-").toFile()
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        val peer = "22222222-2222-4222-8222-222222222222"; val run = UUID.randomUUID().toString()
        val key = SecretKeySpec(ByteArray(32) { 19 }, "AES"); var fail = false
        try {
            val storage = Ablage.fuerTest(context) { if (fail) throw java.io.IOException("Synthetic writer failure"); key }
            storage.setzeNotiz(Notiz("restore-note", text = "Synthetic protected source"))
            storage.personalSyncSnapshot(setOf("notes"), 3); storage.personalSyncAcknowledge(peer)
            storage.loescheNotiz("restore-note"); storage.personalSyncSnapshot(setOf("notes"), 3)
            val before = storage.bestand.value; val saved = requireNotNull(storage.personalActorSavedBookState())
            val meta = before.personalSync.entities.getValue("note\u0000restore-note")
            val proposal = PersonalDeletionProposal(run, UUID.randomUUID().toString(), "note", "restore-note", "", meta.clock,
                meta.prior_hash, meta.deleted_ms, "Synthetic", peer)
            val choice = AppliedPersonalDecision(proposal.proposal_id, "restore", proposal.clock, UUID.randomUUID().toString())
            val claim = PersonalHistoricalRestoreClaim.prepare(peer, run, before, saved, PersonalSync.livePersonalContent(before), listOf(proposal), listOf(choice))
            val bytes = File(directory, "notizen.json").readBytes(); var closed = false
            val guard = { check(closed) { "native_data_owner_not_retired" } }
            assertTrue(runCatching { storage.personalSyncApplyHistoricalRestoreClaim(claim, guard) }.isFailure)
            assertSame(before, storage.bestand.value); assertEquals(saved, storage.personalActorSavedBookState())
            assertArrayEquals(bytes, File(directory, "notizen.json").readBytes())
            closed = true; fail = true
            assertTrue(runCatching { storage.personalSyncApplyHistoricalRestoreClaim(claim, guard) }.isFailure)
            assertSame(before, storage.bestand.value); assertEquals(saved, storage.personalActorSavedBookState())
            assertArrayEquals(bytes, File(directory, "notizen.json").readBytes())
            fail = false
            assertEquals("applied", storage.personalSyncApplyHistoricalRestoreClaim(claim, guard))
            val after = requireNotNull(storage.personalActorSavedBookState())
            assertEquals(saved.getValue("sequence").jsonPrimitive.long + 1, after.getValue("sequence").jsonPrimitive.long)
            assertEquals(saved["book_source"], after["book_source"])
            assertEquals("Synthetic protected source", storage.notiz("restore-note")?.text)
            val afterBytes = File(directory, "notizen.json").readBytes()
            assertEquals("conflict", storage.personalSyncApplyHistoricalRestoreClaim(claim, guard))
            assertEquals(after, storage.personalActorSavedBookState()); assertArrayEquals(afterBytes, File(directory, "notizen.json").readBytes())
            assertEquals(storage.bestand.value, Ablage.fuerTest(context) { key }.bestand.value)
        } finally { directory.deleteRecursively() }
    }
}
