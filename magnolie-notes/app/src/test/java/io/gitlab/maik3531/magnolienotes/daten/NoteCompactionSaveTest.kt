package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.io.IOException
import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class NoteCompactionSaveTest {
    @Test fun `one pre-change snapshot covers all duplicates and a failed snapshot prevents the commit`() {
        for (failSnapshot in listOf(false, true)) {
            val directory = Files.createTempDirectory("note-compaction-save-").toFile()
            try {
                val base: Context = ApplicationProvider.getApplicationContext()
                val context = object : ContextWrapper(base) {
                    override fun getFilesDir(): File = directory
                    override fun getApplicationContext(): Context = this
                }
                val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
                lateinit var store: Ablage
                var snapshots = 0
                store = Ablage.fuerTest(context, { key }, {}, {
                    snapshots++
                    val before = Ablage.json.decodeFromString(Bestand.serializer(), store.journalNutzlast().first)
                    assertEquals(20, before.notizen.size)
                    if (failSnapshot) throw IOException("synthetic snapshot failure")
                })
                repeat(10) { group -> repeat(2) { copy ->
                    store.setzeNotiz(Notiz("note-$group-$copy", titel = "Group $group", text = "Content $group"))
                } }
                // Ten incoming notes replace the ten removed copies in the count: still a data change.
                val records = PersonalSync.reconcile(Bestand(notizen = (0..9).map {
                    Notiz("incoming-$it", titel = "Incoming $it", text = "New content $it")
                }, personalSync = PersonalSyncState(actor_id = "22222222-2222-4222-8222-222222222222")),
                    setOf("notes"), 3).second
                val before = File(directory, "notizen.json").readBytes()
                if (failSnapshot) {
                    assertThrows(IOException::class.java) {
                        store.personalSyncApplyOnce(records, emptyMap(), "batch", setOf("notes"), 3)
                    }
                    assertArrayEquals(before, File(directory, "notizen.json").readBytes())
                    assertEquals(20, store.notizen().size)
                    assertEquals(20, Ablage.fuerTest(context) { key }.notizen().size)
                } else {
                    val result = store.personalSyncApplyOnce(records, emptyMap(), "batch", setOf("notes"), 3)!!
                    assertEquals(20, result.bestand.notizen.size)
                    assertEquals(10, result.bestand.notizen.count { it.id.startsWith("note-") })
                    assertNull(store.personalSyncApplyOnce(emptyList(), emptyMap(), "batch", setOf("notes"), 3))
                    store.personalSyncApplyOnce(emptyList(), emptyMap(), "next-batch", setOf("notes"), 3)
                    assertEquals(20, Ablage.fuerTest(context) { key }.notizen().size)
                    // An editor/navigation route may still hold the removed local ID.
                    assertEquals("note-0-0", store.notiz("note-0-1")?.id)
                    store.sichereNotiz(Notiz("note-0-1", titel = "Group 0", text = "Typed while synchronizing"))
                    assertEquals(20, store.notizen().size)
                    assertEquals("Typed while synchronizing", store.notiz("note-0-0")?.text)
                    store.loescheNotiz("note-0-1")
                    assertEquals(19, store.notizen().size)
                }
                assertEquals(1, snapshots)
            } finally { directory.deleteRecursively() }
        }
    }
}
