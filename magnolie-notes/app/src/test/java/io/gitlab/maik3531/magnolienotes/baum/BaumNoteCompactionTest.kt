package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import java.io.File
import java.nio.file.Files
import javax.crypto.KeyGenerator
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class BaumNoteCompactionTest {
    @Test fun `one tree run snapshots before mixed packets but local edits and other runs break the scope`() {
        val directory = Files.createTempDirectory("baum-run-snapshot-").toFile()
        try {
            val base: Context = ApplicationProvider.getApplicationContext()
            val context = object : ContextWrapper(base) {
                override fun getFilesDir(): File = directory
                override fun getApplicationContext(): Context = this
            }
            val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            lateinit var store: Ablage
            val snapshots = mutableListOf<Bestand>()
            var fail = false
            val before = { if (fail) throw java.io.IOException("fixture snapshot failure")
                snapshots.add(store.bestand.value); Unit }
            store = Ablage.fuerTest(context, { key }, {}, before)
            store.setzeBaum(Baumzustand(partner = listOf("a", "b").map {
                Partner(it, name = it, bestaetigt = true, vertraut = true) }))
            store.setzeNotiz(Notiz("own", titel = "Own", text = "Before"))
            val tree = Baumwerk.fuerTest(store, context, before)
            val run = java.util.UUID.randomUUID().toString()
            fun message(id: String, runId: String = run) = buildJsonObject {
                put("art", "notiz"); put("freigabeId", id); put("quelle", "a"); put("version", 1)
                put("titel", id); put("text", id); put("html", ""); put("anhaenge", JsonArray(emptyList()))
                put("syncLauf", runId)
            }
            for (index in 1L..10L) assertTrue(tree.verarbeiteNachricht("a", message("note-$index"), index, null, null))
            val task = JsonObject(Nutzlast.aufgabeInhalt(Aufgabe("task", titel = "Task"), "a") +
                ("syncLauf" to JsonPrimitive(run)))
            assertTrue(tree.verarbeiteNachricht("a", task, 11, null, null))
            assertEquals(1, snapshots.size); assertEquals(1, snapshots[0].notizen.size)
            assertEquals(11, store.notizen().size); assertEquals(1, store.aufgaben().size)
            store.setzeNotiz(store.notiz("own")!!.copy(text = "Local edit"))
            assertTrue(tree.verarbeiteNachricht("a", message("after-edit"), 12, null, null))
            assertEquals(2, snapshots.size)
            assertEquals("Local edit", snapshots.last().notizen.first { it.id == "own" }.text)
            assertTrue(tree.verarbeiteNachricht("b", message("other-peer"), 1, null, null))
            assertEquals(3, snapshots.size)
            fail = true
            val previous = store.bestand.value
            assertThrows(java.io.IOException::class.java) {
                tree.verarbeiteNachricht("a", message("failed", java.util.UUID.randomUUID().toString()), 13, null, null)
            }
            assertEquals(previous, store.bestand.value)
            assertEquals(12L, store.baum.value.partner.first { it.kennung == "a" }.zaehlerRein)
            fail = false
            assertTrue(tree.verarbeiteNachricht("a", message("retry"), 13, null, null))
            assertEquals(4, snapshots.size)
            val restarted = Baumwerk.fuerTest(store, context, before)
            assertTrue(restarted.verarbeiteNachricht("a", message("after-restart"), 14, null, null))
            assertEquals(5, snapshots.size)
        } finally { directory.deleteRecursively() }
    }

    @Test fun `real tree receipt compacts before editing and preserves independent sources without metadata snapshots`() {
        val directory = Files.createTempDirectory("baum-note-compaction-").toFile()
        try {
            val base: Context = ApplicationProvider.getApplicationContext()
            val context = object : ContextWrapper(base) {
                override fun getFilesDir(): File = directory
                override fun getApplicationContext(): Context = this
            }
            val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            lateinit var store: Ablage
            val snapshots = mutableListOf<List<Notiz>>()
            val before = { snapshots.add(store.notizen().toList()); Unit }
            store = Ablage.fuerTest(context, { key }, {}, before)
            store.setzeBaum(Baumzustand(partner = listOf("a", "b").map {
                Partner(it, name = it, bestaetigt = true, vertraut = true)
            }))
            val first = Notiz("local", titel = "Same", text = "Same", baumQuelle = "a",
                baumFreigabe = Freigabe("share-a", listOf("a"), quellen = listOf(NotizQuelle("a", "share-a", 1, "a", 0))))
            store.setzeNotiz(first)
            store.setzeNotiz(first.copy(id = "own-copy", baumQuelle = "", baumFreigabe = null))
            val tree = Baumwerk.fuerTest(store, context, before)
            fun receive(peer: String, counter: Long, version: Long, text: String, art: String = "notiz_sync") {
                val body = buildJsonObject {
                    put("art", art); put("freigabeId", "share-$peer"); put("quelle", peer)
                    put("version", version); put("geaendert", version * 1000)
                    put("titel", "Same"); put("text", text); put("html", "")
                    put("anhaenge", JsonArray(emptyList()))
                }
                assertTrue(tree.verarbeiteNachricht(peer, body, counter, null, null))
            }
            receive("a", 1, 2, "Changed by a")
            assertEquals(1, snapshots.size); assertEquals(2, snapshots.single().size)
            assertEquals("Changed by a", store.notizen().single().text)
            assertTrue(store.notizen().single().persoenlichVerknuepft)
            val modified = store.notizen().single().geaendert
            val messages = tree.meldungen.value.size
            receive("a", 2, 3, "Changed by a")
            assertEquals(1, snapshots.size); assertEquals(modified, store.notizen().single().geaendert)
            assertEquals(messages, tree.meldungen.value.size)
            receive("b", 1, 50, "Changed by a", "notiz")
            assertEquals(1, snapshots.size); assertEquals(1, store.notizen().size)
            assertEquals(2, store.notizen().single().baumFreigabe!!.quellen.size)
            receive("a", 3, 4, "Next from a")
            assertEquals("Next from a", store.notizen().single().text)
            assertEquals(2, snapshots.size)
            receive("b", 2, 51, "Concurrent from b")
            assertEquals("Next from a", store.notizen().single().text)
            assertEquals(2, snapshots.size)
            val pending = store.baum.value.eingang.single()
            tree.eingangAnnehmen(pending.id)
            assertEquals("Concurrent from b", store.notizen().single().text)
            assertEquals(3, snapshots.size)
            assertTrue(store.baum.value.eingang.isEmpty())
            val loaded = Ablage.fuerTest(context) { key }
            assertEquals(store.notizen(), loaded.notizen())
        } finally { directory.deleteRecursively() }
    }
}
