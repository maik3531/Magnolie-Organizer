package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.KontaktEingang
import io.gitlab.maik3531.magnolienotes.daten.KontaktSpur
import org.junit.Assert.*
import org.junit.Test

class KontaktUebernahmeTest {
    private val alt = 1_770_000_000_000L
    private val jetzt = alt + 100_000
    private val karte = KontaktDaten(vorname = "Anna", nachname = "Person", firma = "Incoming",
        telefone = listOf(KontaktWert("mobil", "+4912345")), notiz = "Incoming note", geburtstag = "1980-01-01")
    private fun eingang(k: KontaktDaten = karte, zeit: Long = alt + 1000) =
        KontaktEingang("peer", "share", 3, "sender", jetzt, k, jetzt, zeit)
    private fun lokal(k: KontaktDaten = karte.copy(firma = "Local", notiz = "Local note"), id: Long = 1) =
        AndroidKontakt("lookup-$id", id, k, providerGeaendert = alt, rawVersionen = mapOf(id to 1))
    private fun plan(kontakte: List<AndroidKontakt>, spuren: List<KontaktSpur> = emptyList(),
                     e: KontaktEingang = eingang()) = KontaktUebernahmePlan.planen(
        KontaktEingangslogik.gruppiere(listOf(e)), KontaktSnapshot(kontakte, true), spuren, jetzt).single()

    @Test fun `new and identical contacts are ready but differing local contents require review`() {
        assertEquals(KontaktEntscheidung.NEU, plan(emptyList()).vorauswahl)
        val gleich = plan(listOf(lokal(karte)))
        assertEquals(KontaktEntscheidung.MISCHEN, gleich.vorauswahl)
        assertTrue(gleich.ziele.single().stark)
        assertNull(plan(listOf(lokal())).vorauswahl)
    }

    @Test fun `names and ambiguous phone identities never enable newest or automatic import`() {
        val name = plan(listOf(lokal(karte.copy(telefone = emptyList()))))
        assertFalse(name.ziele.single().stark)
        assertFalse(KontaktUebernahmePlan.neuesteMoeglich(name, name.ziele.single()))
        assertNull(name.vorauswahl)
        val mehr = plan(listOf(lokal(), lokal(id = 2)))
        assertEquals(2, mehr.ziele.size)
        assertTrue(mehr.ziele.none { it.stark })
        assertNull(mehr.vorauswahl)
    }

    @Test fun `binding contradictions missing targets and recycled raw ids remain manual`() {
        val spur = KontaktSpur(rawContactId = 1, lookupKey = "lookup-1", partner = "peer", freigabeId = "share")
        assertTrue(plan(listOf(lokal(karte.copy(telefone = emptyList()))), listOf(spur)).ziele.single().stark)
        assertFalse(plan(listOf(lokal()), listOf(spur.copy(lookupKey = "old-lookup"))).ziele.single().stark)
        assertNull(plan(emptyList(), listOf(spur)).vorauswahl)
        val widerspruch = plan(listOf(lokal(karte.copy(telefone = emptyList())), lokal(id = 2)), listOf(spur))
        assertTrue(widerspruch.ziele.none { it.stark })
    }

    @Test fun `partial provider reads cannot produce a plan`() {
        assertThrows(IllegalArgumentException::class.java) {
            KontaktUebernahmePlan.planen(KontaktEingangslogik.gruppiere(listOf(eingang())), KontaktSnapshot(emptyList(), false), emptyList())
        }
    }

    @Test fun `merge keeps local scalars combines notes and applies explicit field selections`() {
        val p = plan(listOf(lokal()))
        val wahl = KontaktAuswahl(p.gruppe.id, KontaktEntscheidung.MISCHEN, 1)
        val gemischt = KontaktUebernahmePlan.inhalt(p, wahl)
        assertEquals("Local", gemischt.firma)
        assertEquals("Local note\n\nIncoming note", gemischt.notiz)
        assertEquals(1, gemischt.telefone.size)
        val wiederholt = plan(listOf(lokal(gemischt)))
        assertEquals(gemischt, KontaktUebernahmePlan.inhalt(wiederholt,
            KontaktAuswahl(wiederholt.gruppe.id, KontaktEntscheidung.MISCHEN, 1)))
        val gewaehlt = KontaktUebernahmePlan.inhalt(p, wahl.copy(fernfelder = setOf("firma", "notiz")))
        assertEquals("Incoming", gewaehlt.firma); assertEquals("Incoming note", gewaehlt.notiz)
        assertThrows(IllegalArgumentException::class.java) { KontaktUebernahmePlan.inhalt(p, wahl.copy(fernfelder = setOf("uid"))) }
    }

    @Test fun `newest needs original times and retains an existing photo`() {
        val p = plan(listOf(lokal(karte.copy(firma = "Old", foto = "local-photo"))))
        assertTrue(KontaktUebernahmePlan.neuesteMoeglich(p, p.ziele.single()))
        val neu = KontaktUebernahmePlan.inhalt(p, KontaktAuswahl(p.gruppe.id, KontaktEntscheidung.NEUESTE, 1))
        assertEquals("Incoming", neu.firma); assertEquals("local-photo", neu.foto)
        for (zeit in listOf(0L, alt, jetzt + 300_001)) {
            val unklar = plan(listOf(lokal()), e = eingang(zeit = zeit))
            assertFalse(KontaktUebernahmePlan.neuesteMoeglich(unklar, unklar.ziele.single()))
        }
        val spur = KontaktSpur(rawContactId = 1, inhaltHash = KontaktSync.hash(lokal().daten),
            inhaltGeaendert = 0, providerGeaendert = alt)
        val unbekannt = plan(listOf(lokal()), listOf(spur))
        assertEquals(0, unbekannt.ziele.single().inhaltszeit)
    }

    @Test fun `aggregate replacement is not inferred from one constituent binding`() {
        val kontakt = lokal().copy(rawContactIds = setOf(1, 2), rawVersionen = mapOf(1L to 1, 2L to 2))
        val spur = KontaktSpur(rawContactId = 2, lookupKey = "lookup-1", partner = "peer", freigabeId = "share")
        val p = plan(listOf(kontakt), listOf(spur))
        assertEquals(2L, p.ziele.single().kontakt.rawContactId)
        assertFalse(KontaktUebernahmePlan.neuesteMoeglich(p, p.ziele.single()))
        assertThrows(IllegalArgumentException::class.java) {
            KontaktUebernahmePlan.inhalt(p, KontaktAuswahl(p.gruppe.id, KontaktEntscheidung.ERSETZEN, 2))
        }
    }

    @Test fun `merged fragments cannot invent a whole content timestamp`() {
        val a = eingang(karte.copy(emailEintraege = emptyList()))
        val b = eingang(karte.copy(emailEintraege = listOf(KontaktWert("", "a@example.test"))))
        val kombiniert = KontaktEingangslogik.vereinige(listOf(a.kontakt, b.kontakt)).copy(firma = "Local")
        assertEquals(0, KontaktUebernahmePlan.originalZeit(listOf(a, b), kombiniert, jetzt))
    }

    @Test fun `previous surname is retained as birth name only by explicit choice`() {
        val p = plan(listOf(lokal(karte.copy(nachname = "Old", notiz = "Existing note"))))
        val wahl = KontaktAuswahl(p.gruppe.id, KontaktEntscheidung.MISCHEN, 1, setOf("nachname"))
        assertFalse(KontaktUebernahmePlan.inhalt(p, wahl).notiz.contains("Birth name:"))
        val neu = KontaktUebernahmePlan.inhalt(p, wahl.copy(geburtsnameBehalten = true)) { "Geburtsname: $it" }
        assertEquals("Person", neu.nachname)
        assertTrue(neu.notiz.contains("Existing note")); assertTrue(neu.notiz.contains("Geburtsname: Old"))
        assertThrows(IllegalArgumentException::class.java) {
            KontaktUebernahmePlan.inhalt(p, wahl.copy(entscheidung = KontaktEntscheidung.BEHALTEN, geburtsnameBehalten = true))
        }
    }
}
