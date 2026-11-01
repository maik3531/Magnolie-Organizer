package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
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

/** Actual encrypted document writer, not TelefonWerk/session or handset acceptance. */
@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class PersonalActorTargetObservationWriterTest {
    @Test fun actualSavedWriterIsObservedWithoutWritesAndANewSaveInvalidatesTheOldObservation() {
        val directory = Files.createTempDirectory("notes-native-target-writer-").toFile()
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        try {
            val peer = "22222222-2222-4222-8222-222222222222"
            val run = UUID.randomUUID().toString()
            val key = SecretKeySpec(ByteArray(32) { 19 }, "AES")
            val documents = Ablage.fuerTest(context) { key }
            documents.setzeNotiz(Notiz("own-note", text = "PRIVATE SYNTHETIC ORIGINAL"))
            val selected = PersonalSync.livePersonalContent(documents.bestand.value)
            documents.personalSyncScopedSnapshot(selected, peer, 14)
            // A newly snapshotted local entry has no peer relationship until
            // the existing native acknowledgement path records it durably.
            documents.personalSyncAcknowledge(peer)
            val meta = documents.bestand.value.personalSync.entities.getValue("note\u0000own-note")
            val target = buildJsonObject {
                put("proposal_id", UUID.randomUUID().toString()); put("kind", "note"); put("id", "own-note"); put("parent_id", "")
                put("prior_hash", meta.hash); put("clock", JsonArray(meta.clock.map { buildJsonObject {
                    put("actor_id", it.actor_id); put("counter", it.counter)
                } }))
            }
            // Artificial offscope here tests only the native writer/observation
            // contract. It does not claim real service admission of this scope.
            val scope = PhoneContentScope.create(emptyList(), emptyList())
            fun observer() = PersonalActorIncomingTargetObservation(peer, run, { true }, { "a".repeat(64) },
                { documents.bestand.value }, { documents.personalActorSavedBookState() }, { scope })
            synchronized(Ablage.SCHREIBSPERRE) {
                val saved = requireNotNull(documents.personalActorSavedBookState())
                val bytes = File(directory, "notizen.json").readBytes()
                val before = documents.bestand.value
                val old = observer()
                val observed = old.observeMany(run, listOf(target)).single()
                assertEquals(saved, observed["native_saved_book"])
                assertFalse(observed.toString().contains("PRIVATE"))
                assertArrayEquals(bytes, File(directory, "notizen.json").readBytes())
                assertSame(before, documents.bestand.value)
                assertEquals(saved, documents.personalActorSavedBookState())
                documents.setzeNotiz(before.notizen.single { it.id == "own-note" }.copy(text = "PRIVATE SYNTHETIC NEWER"))
                val after = requireNotNull(documents.personalActorSavedBookState())
                assertTrue(after.getValue("sequence").jsonPrimitive.long > saved.getValue("sequence").jsonPrimitive.long)
                assertTrue(runCatching { old.observeMany(run, listOf(target)) }.isFailure)
                val fresh = observer().observeMany(run, listOf(target)).single()
                assertEquals(after, fresh["native_saved_book"])
                assertEquals(JsonPrimitive(true), fresh["requires_conflict_choice"])
                val reopened = Ablage.fuerTest(context) { key }
                assertEquals("PRIVATE SYNTHETIC NEWER", reopened.bestand.value.notizen.single { it.id == "own-note" }.text)
            }
        } finally { directory.deleteRecursively() }
    }
}
