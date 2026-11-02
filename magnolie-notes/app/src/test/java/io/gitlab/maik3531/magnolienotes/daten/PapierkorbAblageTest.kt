package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class PapierkorbAblageTest {
    private fun probe(block: (Ablage, File, () -> Ablage) -> Unit) {
        val directory = Files.createTempDirectory("magnolie-unified-trash-").toFile()
        try {
            val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
                override fun getApplicationContext(): Context = this
                override fun getFilesDir(): File = directory
            }
            val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            val reopen = { Ablage.fuerTest(context) { key } }
            block(reopen(), directory, reopen)
        } finally { directory.deleteRecursively() }
    }

    private fun fill(storage: Ablage, withNote: Boolean = true) {
        storage.setzePapierkorb(true, 0)
        if (withNote) {
            val note = storage.sichereNotiz(Notiz("synthetic-trash-note", titel = "Synthetic secret note"))
            storage.loescheNotiz(note.id)
        }
        storage.aendereZeiterfassung { it.copy(enabled = true).replace(null,
            Zeiteintrag(startMinute = 1000, endMinute = 1060, type = "Synthetic secret time")) }
        storage.entferneZeitenLokal(storage.bestand.value.zeiterfassung.entries)
    }

    @Test fun mixedAndTimeOnlyTrashAreEmptiedByOnePersistedOperation() {
        for (withNote in listOf(false, true)) probe { storage, directory, reopen ->
            fill(storage, withNote)
            val before = storage.bestand.value
            assertFalse(File(directory, "notizen.json").readText().contains("Synthetic secret"))
            storage.papierkorbLeeren(PapierkorbLogik.kennungen(before))
            val after = storage.bestand.value
            assertEquals(before.copy(papierkorb = emptyList(),
                zeiterfassung = before.zeiterfassung.copy(trash = emptyList())), after)
            assertEquals(after, reopen().bestand.value)
        }
    }

    @Test fun failedMixedClearDoesNotPublishOrPersistHalfAnOperation() = probe { storage, directory, reopen ->
        fill(storage)
        val before = storage.bestand.value
        val bytes = File(directory, "notizen.json").readBytes()
        assertTrue(File(directory, "notizen.json.neu").mkdir())
        assertThrows(java.io.IOException::class.java) { storage.papierkorbLeeren(PapierkorbLogik.kennungen(before)) }
        assertEquals(before, storage.bestand.value)
        assertArrayEquals(bytes, File(directory, "notizen.json").readBytes())
        // Restart may perform its own verified write; remove only our empty fault injector.
        assertTrue(File(directory, "notizen.json.neu").delete())
        assertEquals(before, reopen().bestand.value)
    }

    @Test fun selectionOrPolicyChangesRejectClearAndTimeRemovalWithoutWriting() = probe { storage, directory, _ ->
        fill(storage)
        val before = storage.bestand.value
        val bytes = File(directory, "notizen.json").readBytes()
        assertThrows(IllegalStateException::class.java) { storage.papierkorbLeeren(emptySet()) }
        assertArrayEquals(bytes, File(directory, "notizen.json").readBytes())
        storage.setzePapierkorb(false, 0)
        val off = storage.bestand.value
        assertThrows(IllegalStateException::class.java) { storage.papierkorbLeeren(PapierkorbLogik.kennungen(before)) }
        assertThrows(IllegalStateException::class.java) { storage.zeitPapierkorbEndgueltig(before.zeiterfassung.trash.single().id) }
        assertThrows(IllegalStateException::class.java) { storage.zeitPapierkorbWiederherstellen(before.zeiterfassung.trash.single().id) }
        assertThrows(IllegalStateException::class.java) { storage.papierkorbWiederherstellen(before.papierkorb.single().id) }
        assertThrows(IllegalStateException::class.java) {
            storage.entferneZeitenLokal(emptyList(), expectedTrash = before.papierkorbEinstellungen)
        }
        assertEquals(off, storage.bestand.value)
    }

    @Test fun disabledTrashPreservesOldPayloadsButNewTimeRemovalIsPermanentAcrossRestart() = probe { storage, _, reopen ->
        fill(storage)
        storage.setzePapierkorb(false, 0)
        val before = storage.bestand.value
        storage.aendereZeiterfassung { it.replace(null,
            Zeiteintrag(startMinute = 2000, endMinute = 2060, type = "New synthetic time")) }
        val removed = storage.bestand.value.zeiterfassung.entries.single()
        storage.entferneZeitenLokal(listOf(removed), expectedTrash = before.papierkorbEinstellungen)
        storage.bereinigePapierkorb()
        val after = reopen().bestand.value
        assertEquals(before.papierkorb, after.papierkorb)
        assertEquals(before.zeiterfassung.trash, after.zeiterfassung.trash)
        assertTrue(after.zeiterfassung.entries.isEmpty())
        assertTrue(removed.id in after.zeiterfassung.removedIds)
    }
}
