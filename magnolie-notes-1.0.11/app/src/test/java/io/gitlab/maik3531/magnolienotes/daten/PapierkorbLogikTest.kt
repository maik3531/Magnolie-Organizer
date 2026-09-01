package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PapierkorbLogikTest {
    @Test fun `note and attachments move together and restore same id`() {
        val note = Notiz("n", titel = "N", anhaenge = listOf(Anhang("a", "A")))
        val deleted = PapierkorbLogik.loescheNotiz(Bestand(notizen = listOf(note)), "n", 100)
        assertTrue(deleted.notizen.isEmpty())
        assertEquals(note, deleted.papierkorb.single().notiz)
        val restored = PapierkorbLogik.wiederherstellen(deleted, deleted.papierkorb.single().id, 200)!!
        assertEquals(note, restored.notizen.single())
        assertTrue(restored.papierkorb.isEmpty())
    }

    @Test fun `attachment removal has own trash entry and notebook cascade is blocked`() {
        val note = Notiz("n", notizbuchId = "b", anhaenge = listOf(Anhang("a", "A")))
        val input = Bestand(notizen = listOf(note), notizbuecher = listOf(Notizbuch("b", "B")))
        val deleted = PapierkorbLogik.loescheAnhang(input, "n", "a", 100)
        assertTrue(deleted.notizen.single().anhaenge.isEmpty())
        assertEquals("attachment", deleted.papierkorb.single().art)
        assertNull(PapierkorbLogik.loescheNotizbuch(input, "b"))
    }

    @Test fun `retention zero is manual and configured age expires`() {
        val deleted = PapierkorbLogik.loescheAufgabe(Bestand(aufgaben = listOf(Aufgabe("t"))), "t", 1)
        assertEquals(1, PapierkorbLogik.bereinigen(deleted.copy(
            papierkorbEinstellungen = PapierkorbEinstellungen(true, 0)), Long.MAX_VALUE).papierkorb.size)
        assertTrue(PapierkorbLogik.bereinigen(deleted.copy(
            papierkorbEinstellungen = PapierkorbEinstellungen(true, 7)), 8 * 86_400_000L).papierkorb.isEmpty())
    }
}
