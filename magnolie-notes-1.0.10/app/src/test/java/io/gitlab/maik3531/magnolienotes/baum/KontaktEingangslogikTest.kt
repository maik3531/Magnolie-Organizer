package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.Eingangsstueck
import io.gitlab.maik3531.magnolienotes.daten.KontaktAblehnung
import io.gitlab.maik3531.magnolienotes.daten.KontaktEingang
import io.gitlab.maik3531.magnolienotes.daten.KontaktLoeschStand
import io.gitlab.maik3531.magnolienotes.daten.KontaktSpur
import io.gitlab.maik3531.magnolienotes.daten.KontaktVorschlag
import io.gitlab.maik3531.magnolienotes.daten.Partner
import io.gitlab.maik3531.magnolienotes.daten.Sendung
import org.junit.Assert.*
import org.junit.Test

class KontaktEingangslogikTest {
    private fun karte(id: String, daten: KontaktDaten, version: Long = 1, partner: String = "p") =
        KontaktEingang(partner, id, version, "q", 1, daten, 1)
    private fun marcel(vararg daten: KontaktDaten) = daten.mapIndexed { i, k -> karte("m$i", k) }

    @Test fun `fragmentierte Marcel Karten werden eine sichere Person`() {
        val gruppen = KontaktEingangslogik.gruppiere(marcel(
            KontaktDaten(vorname = "Marcel", nachname = "Muster", telefone = listOf(KontaktWert("mobil", "+49 170 1"))),
            KontaktDaten(vorname = " marcel ", nachname = "MUSTER", emailEintraege = listOf(KontaktWert("", "m@example.org"))),
            KontaktDaten(vorname = "Marcel", nachname = "Muster", foto = "bild")
        ))
        assertEquals(1, gruppen.size)
        assertEquals(KontaktGruppenArt.SICHER, gruppen.single().art)
        assertEquals(3, gruppen.single().karten.size)
        assertEquals(1, gruppen.single().kontakt.telefone.size)
        assertEquals(1, gruppen.single().kontakt.emailEintraege.size)
    }

    @Test fun `gleiche volle Namen bleiben zur Pruefung getrennt importierbar`() {
        val gruppe = KontaktEingangslogik.gruppiere(marcel(
            KontaktDaten(vorname = "Marcel", nachname = "Muster", firma = "A", telefone = listOf(KontaktWert("", "111")), emailEintraege = listOf(KontaktWert("", "a@x"))),
            KontaktDaten(vorname = "Marcel", nachname = "Muster", firma = "A", telefone = listOf(KontaktWert("", "222")), emailEintraege = listOf(KontaktWert("", "b@x")))
        )).single()
        assertEquals(KontaktGruppenArt.PRUEFEN, gruppe.art)
        assertTrue(gruppe.zusammenfuehrbar)
    }

    @Test fun `skalare Bilder und Notizen erzeugen verlustbehafteten Konflikt`() {
        val gruppe = KontaktEingangslogik.gruppiere(marcel(
            KontaktDaten(vorname = "Marcel", nachname = "Muster", firma = "A", foto = "eins", notiz = "N1"),
            KontaktDaten(vorname = "Marcel", nachname = "Muster", firma = "B", foto = "zwei", notiz = "N2")
        )).single()
        assertEquals(KontaktGruppenArt.KONFLIKT, gruppe.art)
        assertFalse(gruppe.zusammenfuehrbar)
        assertTrue(gruppe.konflikte.map { it.feld }.containsAll(listOf("Firma", "Bild", "Notiz")))
    }

    @Test fun `harte Telefonnummer und Email gruppieren konfliktfrei und deduplizieren`() {
        val gruppen = KontaktEingangslogik.gruppiere(listOf(
            karte("a", KontaktDaten(vorname = "A", telefone = listOf(KontaktWert("", "+49 123")))),
            karte("b", KontaktDaten(vorname = "A", telefone = listOf(KontaktWert("", "0049-123")), emailEintraege = listOf(KontaktWert("", "A@X.DE")))),
            karte("c", KontaktDaten(vorname = "A", emailEintraege = listOf(KontaktWert("", "a@x.de"))))
        ))
        assertEquals(1, gruppen.size)
        assertEquals(KontaktGruppenArt.SICHER, gruppen.single().art)
        assertEquals(1, gruppen.single().kontakt.telefone.size)
        assertEquals(1, gruppen.single().kontakt.emailEintraege.size)
    }

    @Test fun `schwache Namensbruecke verbindet keine harten Gruppen transitiv`() {
        val gruppen = KontaktEingangslogik.gruppiere(listOf(
            karte("a", KontaktDaten(vorname = "Marcel", nachname = "M", telefone = listOf(KontaktWert("", "111")))),
            karte("b", KontaktDaten(vorname = "Marcel", nachname = "M", telefone = listOf(KontaktWert("", "111")), firma = "A")),
            karte("c", KontaktDaten(vorname = "Marcel", nachname = "M", telefone = listOf(KontaktWert("", "222")), firma = "B"))
        ))
        assertEquals(1, gruppen.size)
        assertEquals(KontaktGruppenArt.KONFLIKT, gruppen.single().art)
        assertEquals(3, gruppen.single().karten.size)
    }

    @Test fun `gleiche Id ist nur die neueste Revision derselben Karte`() {
        val gruppe = KontaktEingangslogik.gruppiere(listOf(
            karte("a", KontaktDaten(vorname = "Alt"), 1),
            karte("a", KontaktDaten(vorname = "Neu"), 2)
        )).single()
        assertEquals(1, gruppe.karten.size)
        assertEquals("Neu", gruppe.kontakt.vorname)
    }

    @Test fun `wartender gebundener oder abgelehnter Stand macht Revision idempotent`() {
        val n = KontaktNachricht("f", 2, "q", 1, KontaktDaten(vorname = "A"))
        assertFalse(KontaktEingangslogik.sollAufnehmen(n, karte("f", n.kontakt, 2), null, null, null))
        assertFalse(KontaktEingangslogik.sollAufnehmen(n, null, 2, "q", null))
        assertFalse(KontaktEingangslogik.sollAufnehmen(n, null, null, null, KontaktAblehnung("p", "f", 2, "q")))
        assertTrue(KontaktEingangslogik.sollAufnehmen(n.copy(version = 3), null, null, null,
            KontaktAblehnung("p", "f", 2, "q")))
    }

    @Test fun `eine Gruppe legt genau einen RawContact an und bindet alle Aliase`() {
        class Fake : KontaktSchreiber {
            var anzahl = 0
            override fun anlegen(k: KontaktDaten): AndroidKontakt {
                anzahl++; return AndroidKontakt("lookup", 42, k)
            }
            override fun mischen(rawId: Long, fern: KontaktDaten) = AndroidKontakt("lookup", rawId, fern)
            override fun fotoErgaenzen(rawId: Long, foto: String) = null
        }
        val fake = Fake()
        val karten = marcel(KontaktDaten(vorname = "Marcel", telefone = listOf(KontaktWert("", "1"))),
            KontaktDaten(vorname = "Marcel", emailEintraege = listOf(KontaktWert("", "m@x"))))
        val ergebnis = KontaktEingangslogik.importiere(karten, fake)
        assertEquals(1, fake.anzahl)
        assertEquals(setOf("m0", "m1"), ergebnis.spuren.map { it.freigabeId }.toSet())
        assertTrue(ergebnis.spuren.all { it.rawContactId == 42L })
    }

    @Test fun `getrennt importieren erzeugt je Rohkarte einen Kontakt`() {
        class Fake : KontaktSchreiber {
            var anzahl = 0L
            override fun anlegen(k: KontaktDaten) = AndroidKontakt("l", ++anzahl, k)
            override fun mischen(rawId: Long, fern: KontaktDaten) = AndroidKontakt("l", rawId, fern)
            override fun fotoErgaenzen(rawId: Long, foto: String) = null
        }
        val fake = Fake(); val karten = marcel(KontaktDaten(vorname = "M"), KontaktDaten(vorname = "M"))
        karten.forEach { KontaktEingangslogik.importiere(listOf(it), fake) }
        assertEquals(2L, fake.anzahl)
    }

    @Test fun `hoehere Revision aktualisiert ausdruecklich denselben gebundenen RawContact`() {
        class Fake : KontaktSchreiber {
            var angelegt = 0; var gemischt = 0L
            override fun anlegen(k: KontaktDaten): AndroidKontakt { angelegt++; return AndroidKontakt("l", 99, k) }
            override fun mischen(rawId: Long, fern: KontaktDaten): AndroidKontakt {
                gemischt = rawId; return AndroidKontakt("l", rawId, fern)
            }
            override fun fotoErgaenzen(rawId: Long, foto: String) = null
        }
        val fake = Fake()
        val ergebnis = KontaktEingangslogik.importiere(listOf(karte("f", KontaktDaten(vorname = "Neu"), 2)), fake, 42)
        assertEquals(0, fake.angelegt); assertEquals(42L, fake.gemischt)
        assertEquals(42L, ergebnis.spuren.single().rawContactId)
    }

    @Test fun `Partnerbereinigung entfernt nur Metadaten und keine Telefonoperation`() {
        val z = Baumzustand(
            partner = listOf(Partner("p"), Partner("x")),
            postfach = listOf(Sendung("s", "t", "p", "a", "")),
            eingang = listOf(Eingangsstueck("e", "p")),
            kontaktEingang = listOf(karte("f", KontaktDaten())),
            kontaktAblehnungen = listOf(KontaktAblehnung("p", "f", 1, "q")),
            kontaktSpuren = listOf(KontaktSpur(partner = "p")),
            kontaktVorschlaege = listOf(KontaktVorschlag(partner = "p")),
            kontaktLoeschStaende = listOf(KontaktLoeschStand(partner = "p"))
        )
        val neu = KontaktEingangslogik.bereinigePartner(z, "p")
        assertEquals(listOf("x"), neu.partner.map { it.kennung })
        assertTrue(neu.postfach.isEmpty() && neu.eingang.isEmpty() && neu.kontaktEingang.isEmpty())
        assertTrue(neu.kontaktAblehnungen.isEmpty() && neu.kontaktSpuren.isEmpty() && neu.kontaktVorschlaege.isEmpty())
    }

    @Test fun `Snapshot aggregiert RawContacts derselben ContactId einmal`() {
        val roh = listOf(
            AndroidKontakt("l", 1, KontaktDaten(vorname = "M", telefone = listOf(KontaktWert("", "1"))), 9),
            AndroidKontakt("l", 2, KontaktDaten(nachname = "Muster", emailEintraege = listOf(KontaktWert("", "m@x"))), 9),
            AndroidKontakt("z", 3, KontaktDaten(vorname = "Z"), 10)
        )
        val aus = AndroidKontakte.aggregiere(roh)
        assertEquals(2, aus.size)
        val m = aus.first { it.contactId == 9L }
        assertEquals(setOf(1L, 2L), m.rawContactIds)
        assertEquals("M", m.daten.vorname); assertEquals("Muster", m.daten.nachname)
    }
}
