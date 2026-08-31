package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.daten.Freigabe
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SynchronisationTest {
    @Test
    fun `neue Freigabe erhaelt stabile Kennung Fassung und Quelle`() {
        val erstes = Synchronisation.notizVorbereiten(Notiz("n1"), "p1", "ich", 123)
        val zweites = Synchronisation.notizVorbereiten(erstes.notiz, "p1", "ich", 999)

        assertEquals("notiz", erstes.art)
        assertEquals("notiz_sync", zweites.art)
        assertEquals(erstes.notiz.baumFreigabe?.id, zweites.notiz.baumFreigabe?.id)
        assertEquals(1L, zweites.notiz.baumVersion)
        assertEquals(123L, zweites.notiz.baumGeaendert)
        assertEquals("ich", zweites.notiz.baumQuelle)
    }

    @Test
    fun `neuer Partner bekommt Angebot ohne bestehende Fassung zu erhoehen`() {
        val notiz = Notiz(
            "n1", baumFreigabe = Freigabe("stabil", listOf("p1")),
            baumVersion = 7, baumQuelle = "quelle", baumGeaendert = 100
        )
        val vorbereitet = Synchronisation.notizVorbereiten(notiz, "p2", "ich", 999)

        assertEquals("notiz", vorbereitet.art)
        assertEquals("stabil", vorbereitet.notiz.baumFreigabe?.id)
        assertEquals(7L, vorbereitet.notiz.baumVersion)
        assertEquals(listOf("p1", "p2"), vorbereitet.notiz.baumFreigabe?.partner)
    }

    @Test
    fun `Vollsync filtert fremde Aufgaben`() {
        val eigen = Aufgabe("eigen")
        val fremd = Aufgabe("lokal", fremdId = "fern", herkunft = "p1")
        val auswahl = Synchronisation.eigeneAufgaben(listOf(eigen, fremd))

        assertEquals(listOf(eigen), auswahl)
        assertFalse(eigen.istFremd)
        assertTrue(fremd.istFremd)
    }

    @Test
    fun `Antwort auf Sync Anfrage erzeugt keine weitere Anfrage`() {
        val plan = Synchronisation.planen(
            listOf(Notiz("n1")), listOf(Aufgabe("a1")), "p1", "ich", 123,
            mitAnfrage = false
        )

        assertFalse(plan.syncAnfrage)
        assertEquals(1, plan.notizen.size)
        assertEquals(1, plan.aufgaben.size)
    }
}
