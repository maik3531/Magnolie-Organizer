package io.gitlab.maik3531.magnolienotes.daten

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class SingleItemActionsTest {
    private lateinit var storage: Ablage
    @Before fun setup() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.filesDir.deleteRecursively(); context.filesDir.mkdirs()
        storage = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 31 }, "AES") }
    }
    @Test fun snapshotsSelectOnlyTheChosenEntryAndItsRequiredNotebook() {
        val first = storage.legeNotizbuchAn("Selected notebook")
        val second = storage.legeNotizbuchAn("Private notebook")
        storage.setzeNotiz(Notiz("selected", "Selected", "Chosen", notizbuchId = first.id))
        storage.setzeNotiz(Notiz("other", "Private", "Never transfer", notizbuchId = second.id))
        storage.setzeAufgabe(Aufgabe("selected-task", "Selected task"))
        storage.setzeAufgabe(Aufgabe("other-task", "Private task"))
        val note = storage.personalSyncSingleSnapshot("note", "selected", "peer", 14)
        assertEquals(setOf("selected", first.id), note.records.map { it.id }.toSet())
        assertTrue(note.records.none { it.kind == "task" })
        val task = storage.personalSyncSingleSnapshot("task", "selected-task", "peer", 14)
        assertEquals(listOf("selected-task"), task.records.map { it.id })
        assertEquals(2, storage.notizen().size)
        assertEquals(2, storage.bestand.value.aufgaben.size)
    }
    @Test fun changedNotesAndTasksCannotBeDeletedByAnOlderConfirmation() {
        storage.setzeNotiz(Notiz("n", "Before"))
        storage.setzeAufgabe(Aufgabe("t", "Before"))
        val note = storage.notiz("n")!!; val task = storage.aufgabe("t")!!
        storage.setzeNotiz(note.copy(titel = "Concurrent edit"))
        storage.setzeAufgabe(task.copy(titel = "Concurrent edit"))
        assertFalse(storage.loescheNotizWennUnveraendert(note))
        assertFalse(storage.loescheAufgabeWennUnveraendert(task))
        assertEquals("Concurrent edit", storage.notiz("n")!!.titel)
        assertEquals("Concurrent edit", storage.aufgabe("t")!!.titel)
        assertTrue(storage.loescheNotizWennUnveraendert(storage.notiz("n")!!))
        assertTrue(storage.loescheAufgabeWennUnveraendert(storage.aufgabe("t")!!))
        assertNull(storage.notiz("n")); assertNull(storage.aufgabe("t"))
    }
    @Test fun branchEntriesAndMissingEntriesCannotBecomeImplicitPersonalSends() {
        storage.setzeNotiz(Notiz("tree-note", baumQuelle = "foreign"))
        storage.setzeAufgabe(Aufgabe("tree-task", vonZweig = "foreign"))
        for ((kind, id) in listOf("note" to "tree-note", "task" to "tree-task", "note" to "missing")) {
            assertTrue(runCatching { storage.personalSyncSingleSnapshot(kind, id, "peer", 14) }.isFailure)
        }
    }
}
