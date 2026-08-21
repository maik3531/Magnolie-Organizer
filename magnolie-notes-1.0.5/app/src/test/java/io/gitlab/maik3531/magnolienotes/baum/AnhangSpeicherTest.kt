package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Anhang
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AnhangSpeicherTest {
    private fun anhang(id: String, zeichen: Int) = Anhang(
        id, "$id.png", "image", "data:image/png;base64," + "A".repeat(zeichen)
    )

    @Test fun `Reserve von 256 MiB wird niemals angegriffen`() {
        assertFalse(AnhangSpeicher.entscheide(emptyList(), emptyList(), listOf(anhang("a", 4)),
            AnhangSpeicher.RESERVE_BYTES).erlaubt)
    }

    @Test fun `Notizgrenze bleibt bei 24 Millionen Zeichen`() {
        val frei = AnhangSpeicher.RESERVE_BYTES + 10L * 1024 * 1024 * 1024
        assertTrue(AnhangSpeicher.entscheide(emptyList(), emptyList(), listOf(anhang("a", 23_999_000)), frei).erlaubt)
        assertFalse(AnhangSpeicher.entscheide(emptyList(), emptyList(), listOf(anhang("a", 24_000_001)), frei).erlaubt)
    }

    @Test fun `ein Prozent des Speichers begrenzt eine neue Notiz dynamisch`() {
        val frei = AnhangSpeicher.RESERVE_BYTES + 100_000_000L
        assertTrue(AnhangSpeicher.entscheide(emptyList(), emptyList(), listOf(anhang("a", 1_300_000)), frei).erlaubt)
        assertFalse(AnhangSpeicher.entscheide(emptyList(), emptyList(), listOf(anhang("a", 1_400_000)), frei).erlaubt)
    }

    @Test fun `bestehende Anhaenge zaehlen und Ablehnung ist atomar`() {
        val alt = anhang("alt", 8_000_000)
        val neu = anhang("neu", 8_000_000)
        val frei = AnhangSpeicher.RESERVE_BYTES + 70_000_000L
        val entscheidung = AnhangSpeicher.entscheide(listOf(alt), listOf(alt), listOf(alt, neu), frei)
        assertFalse(entscheidung.erlaubt)
        assertTrue(entscheidung.bisherBytes > 0)
        assertTrue(entscheidung.danachBytes > entscheidung.bisherBytes)
    }

    @Test fun `appweite Grenze ist hoechstens 512 MiB`() {
        val e = AnhangSpeicher.entscheide(emptyList(), emptyList(), emptyList(), Long.MAX_VALUE)
        assertTrue(e.appGrenzeBytes <= 512L * 1024 * 1024)
    }

    @Test fun `Transportgrenzen sind strikt vierzig MiB`() {
        assertTrue(Server.NACHRICHT_MAX == 40 * 1024 * 1024)
        assertTrue(BluetoothTransport.RAHMEN_MAX == 40 * 1024 * 1024)
    }
}
