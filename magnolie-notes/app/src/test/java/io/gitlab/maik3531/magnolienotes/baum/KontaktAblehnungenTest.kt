package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.KontaktAblehnung
import io.gitlab.maik3531.magnolienotes.daten.KontaktEingang
import org.junit.Assert.*
import org.junit.Test

class KontaktAblehnungenTest {
    private fun karte(text: String, partner: String = "peer", id: String = "share") =
        KontaktEingang(partner = partner, freigabeId = id, version = 1, quelle = "origin",
            kontakt = KontaktDaten(vorname = "Person", notiz = text))

    private fun nachricht(karte: KontaktEingang, version: Long = karte.version) =
        KontaktNachricht(karte.freigabeId, version, karte.quelle, 999999, karte.kontakt)

    @Test fun `rejection survives reload and ignores changed transport revisions`() {
        val original = karte("Original")
        val decisions = KontaktEingangslogik.merkeAblehnungen(emptyList(), listOf(original))
        val serialized = Kanonisch.json.encodeToString(Baumzustand.serializer(), Baumzustand(kontaktAblehnungen = decisions))
        val restored = Kanonisch.json.decodeFromString(Baumzustand.serializer(), serialized).kontaktAblehnungen
        for (version in listOf(1L, 2L, 1000L)) {
            val incoming = nachricht(original, version)
            val rejected = KontaktEingangslogik.findeAblehnung(restored, "peer", incoming)
            assertNotNull(rejected)
            assertFalse(KontaktEingangslogik.sollAufnehmen(incoming, null, null, null, rejected))
        }
    }

    @Test fun `changed content another sender and another share remain reviewable`() {
        val original = karte("Original")
        val decisions = KontaktEingangslogik.merkeAblehnungen(emptyList(), listOf(original))
        for (changed in listOf(karte("Changed"), karte("Original", "other"), karte("Original", id = "other"),
            original.copy(kontakt = original.kontakt.copy(jubilaeum = "--06-07")))) {
            val incoming = nachricht(changed)
            val rejected = KontaktEingangslogik.findeAblehnung(decisions, changed.partner, incoming)
            assertNull(rejected)
            assertTrue(KontaktEingangslogik.sollAufnehmen(incoming, null, null, null, rejected))
        }
        assertTrue(KontaktEingangslogik.sollAufnehmen(nachricht(karte("Changed")), null, null, null, decisions.single()))
    }

    @Test fun `more than 300 rejected versions persist and acceptance retires only matching content`() {
        var decisions = emptyList<KontaktAblehnung>()
        repeat(320) { decisions = KontaktEingangslogik.merkeAblehnungen(decisions, listOf(karte("Body $it"))) }
        assertEquals(320, decisions.size)
        decisions = KontaktEingangslogik.merkeAblehnungen(decisions, listOf(karte("Body 0")))
        assertEquals(320, decisions.size)
        decisions = KontaktEingangslogik.ohneAngenommeneAblehnungen(decisions, listOf(karte("Body 1")))
        assertEquals(319, decisions.size)
        assertNull(KontaktEingangslogik.findeAblehnung(decisions, "peer", nachricht(karte("Body 1"), 1000)))
        assertNotNull(KontaktEingangslogik.findeAblehnung(decisions, "peer", nachricht(karte("Body 0"), 1000)))
        assertNotNull(KontaktEingangslogik.findeAblehnung(decisions, "peer", nachricht(karte("Body 319"), 1000)))
    }

    @Test fun `legacy decisions retain revision guards until explicitly superseded`() {
        val legacy = KontaktAblehnung("peer", "share", 5, "origin")
        assertFalse(KontaktEingangslogik.sollAufnehmen(nachricht(karte("Old"), 5), null, null, null, legacy))
        assertTrue(KontaktEingangslogik.sollAufnehmen(nachricht(karte("New"), 6), null, null, null, legacy))
        val replaced = KontaktEingangslogik.merkeAblehnungen(listOf(legacy), listOf(karte("New")))
        assertEquals(1, replaced.size)
        assertEquals(64, replaced.single().inhaltHash.length)
    }

    @Test fun `stale group action cannot target a replaced card or remove its pending revision`() {
        val old = karte("Old")
        val changed = karte("Changed")
        assertNotEquals(KontaktEingangslogik.gruppiere(listOf(old)).single().id,
            KontaktEingangslogik.gruppiere(listOf(changed)).single().id)
        assertEquals(KontaktEingangslogik.importOperation(listOf(old)),
            KontaktEingangslogik.importOperation(listOf(old.copy(empfangen = 123456))))
        assertNotEquals(KontaktEingangslogik.gruppiere(listOf(old)).single().id,
            KontaktEingangslogik.gruppiere(listOf(old.copy(version = 2))).single().id)
        assertEquals(listOf(changed), KontaktEingangslogik.ohneBearbeiteteKarten(listOf(changed), listOf(old)))
        assertTrue(KontaktEingangslogik.ohneBearbeiteteKarten(listOf(old), listOf(old)).isEmpty())
    }
}
