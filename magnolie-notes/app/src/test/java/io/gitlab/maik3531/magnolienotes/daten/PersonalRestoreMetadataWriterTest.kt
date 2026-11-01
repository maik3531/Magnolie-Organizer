package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.*
import java.io.File
import java.nio.file.Files
import java.util.UUID
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class PersonalRestoreMetadataWriterTest {
    @Test fun restoredNoteTaskAndAttachmentRemainLiveAfterEncryptedRestartAndExactRetryDoesNotWriteAgain() {
        val peer = "22222222-2222-4222-8222-222222222222"
        val fixture = Json.parseToJsonElement(requireNotNull(javaClass.getResource("/personal-sync-contract.json")).readText()).jsonObject
        val image = fixture.getValue("format2").jsonObject.getValue("data_url").jsonPrimitive.content
        for (kind in listOf("note", "task", "attachment")) {
            val directory = Files.createTempDirectory("notes-restore-metadata-").toFile()
            val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
                override fun getApplicationContext(): Context = this
                override fun getFilesDir(): File = directory
            }
            val key = SecretKeySpec(ByteArray(32) { 19 }, "AES")
            try {
                val storage = Ablage.fuerTest(context) { key }
                storage.setzeNotiz(Notiz("own-note", text = "Synthetic original",
                    anhaenge = listOf(Anhang("own-file", "sample.png", "image", image))))
                storage.setzeAufgabe(Aufgabe("own-task", titel = "Synthetic original task"))
                storage.personalSyncSnapshot(setOf("notes", "tasks"), 3); storage.personalSyncAcknowledge(peer)
                when (kind) { "note" -> storage.loescheNotiz("own-note"); "task" -> storage.loescheAufgabe("own-task")
                    else -> storage.loescheAnhang("own-note", "own-file") }
                storage.personalSyncSnapshot(setOf("notes", "tasks"), 3)
                val id = when (kind) { "note" -> "own-note"; "task" -> "own-task"; else -> "own-file" }
                val parent = if (kind == "attachment") "own-note" else ""
                val entityKey = kind + "\u0000" + (if (parent.isEmpty()) "" else parent + "\u0000") + id
                val old = storage.bestand.value.personalSync.entities.getValue(entityKey)
                assertEquals("deleted", old.state)
                val run = UUID.randomUUID().toString(); val decision = UUID.randomUUID().toString()
                val proposal = PersonalDeletionProposal(run, UUID.randomUUID().toString(), kind, id, parent,
                    old.clock, old.prior_hash, old.deleted_ms, "Synthetic remote proposal", peer)
                storage.personalSyncStageProposals(run, peer, listOf(proposal))
                assertEquals("applied", storage.personalSyncDecide(peer, proposal.proposal_id, decision, "restore"))
                val restored = storage.bestand.value.personalSync.entities.getValue(entityKey)
                assertEquals("live", restored.state); assertEquals("restored", restored.status)
                assertEquals("dominates", PersonalSync.compare(restored.clock, old.clock))
                val bytes = File(directory, "notizen.json").readBytes(); val saved = storage.personalActorSavedBookState()
                assertEquals("applied", storage.personalSyncDecide(peer, proposal.proposal_id, decision, "restore"))
                assertArrayEquals(bytes, File(directory, "notizen.json").readBytes()); assertEquals(saved, storage.personalActorSavedBookState())
                val reopened = Ablage.fuerTest(context) { key }
                assertEquals(restored, reopened.bestand.value.personalSync.entities.getValue(entityKey))
                val snapshot = reopened.personalSyncSnapshot(setOf("notes", "tasks"), 3)
                assertEquals("live", reopened.bestand.value.personalSync.entities.getValue(entityKey).state)
                if (kind == "attachment") assertTrue(snapshot.single { it.kind == "note" && it.id == "own-note" }.value
                    .getValue("attachments").jsonArray.any { it.jsonObject.getValue("attachment_id").jsonPrimitive.content == id })
                else assertTrue(snapshot.any { it.kind == kind && it.id == id })
            } finally { directory.deleteRecursively() }
        }
    }
}
