package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.util.Base64

class ModellTest {
    @Test
    fun `alte Partnerdaten erhalten getrennte sichere Vorgaben`() {
        val partner = Json { ignoreUnknownKeys = true }.decodeFromString<Partner>(
            """{"kennung":"p1","adresse":"192.0.2.1","port":8737}"""
        )

        assertEquals("192.0.2.1", partner.adresse)
        assertEquals("", partner.fernAdresse)
        assertEquals(8737, partner.fernPort)
        assertFalse(partner.vertraut)
        assertFalse(partner.kontaktSync)
        assertFalse(partner.kontaktLoeschSync)
    }

    @Test
    fun `alte Baumdaten schalten WLAN Automatik nicht ungefragt ein`() {
        val zustand = Json.decodeFromString<Baumzustand>("{}")
        assertFalse(zustand.automatischWlan)
        assertEquals(0L, zustand.letzteAutoSync)
        assertEquals(emptyList<KontaktSpur>(), zustand.kontaktSpuren)
        assertEquals(emptyList<KontaktEingang>(), zustand.kontaktEingang)
        assertEquals(emptyList<KontaktAblehnung>(), zustand.kontaktAblehnungen)
        assertEquals(emptyList<KontaktVorschlag>(), zustand.kontaktVorschlaege)
        assertEquals(emptyList<KontaktLoeschStand>(), zustand.kontaktLoeschStaende)
    }

    @Test fun `reine Attachment Shares deduplizieren nach Inhalt und bleiben serialisierbar`() {
        val a = Anhang("a", "a.png", "image", "data:image/png;base64," + Base64.getEncoder().encodeToString(byteArrayOf(1)))
        val b = a.copy(id = "b", name = "b.png", daten = "data:image/png;base64," + Base64.getEncoder().encodeToString(byteArrayOf(2)))
        val schluesselA = Ablage.einfuhrSchluessel("Geteilt", "", listOf(a))
        val schluesselB = Ablage.einfuhrSchluessel("Geteilt", "", listOf(b))
        assertFalse(schluesselA == schluesselB)

        val bestand = Bestand(notizen = listOf(Notiz("n", anhaenge = listOf(a), einfuhrSchluessel = schluesselA)))
        val zurueck = Ablage.json.decodeFromString<Bestand>(Ablage.json.encodeToString(Bestand.serializer(), bestand))
        assertEquals(a, zurueck.notizen.single().anhaenge.single())
    }

    @Test fun `Personal Sync Felder und lokale Felder überstehen JSON Rundlauf`() {
        val anhang = Anhang("a", "a.png", "image", "data:image/png;base64,AA==")
        val bestand = Bestand(notizen = listOf(Notiz("n", symbol = "idee", angelegt = 11,
            geaendert = 12, anhaenge = listOf(anhang), baumQuelle = "zweig")),
            aufgaben = listOf(Aufgabe("t", vorlaufTage = 4, erinnerungsMinute = 777,
                angelegt = 21, geaendert = 22, herkunft = "h", vonZweig = "v",
                fremdId = "f", delegiertAn = "d")))
        val zurueck = Ablage.json.decodeFromString<Bestand>(
            Ablage.json.encodeToString(Bestand.serializer(), bestand))
        assertEquals(bestand, zurueck)
    }
}
