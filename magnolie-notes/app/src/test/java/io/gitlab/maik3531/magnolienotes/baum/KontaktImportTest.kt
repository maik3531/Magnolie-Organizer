package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class KontaktImportTest {
    private fun kontakt(source: String = "source-1", lookup: String = "lookup-1", raw: Long = 7) = AndroidKontakt(
        lookup, raw, KontaktDaten(vorname = "Ada", nachname = "Lovelace"),
        herkuenfte = listOf(KontaktHerkunft("com.example", "Privat", "set", source, lookup)))

    @Test fun `Manifest erlaubt getrennte Lese- und Schreibfreigabe fuer Kontakte`() {
        val manifest = File("app/src/main/AndroidManifest.xml").readText()
        val quelltext = File("app/src/main/java").walkTopDown().filter { it.extension == "kt" }
            .joinToString("\n") { it.readText() }
        assertTrue(manifest.contains("android.permission.READ_CONTACTS"))
        assertTrue(manifest.contains("android.permission.WRITE_CONTACTS"))
        assertTrue(quelltext.contains("Manifest.permission.WRITE_CONTACTS"))
        val activity = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/MainActivity.kt").readText()
        assertTrue(activity.contains("kontaktLeseFreigabe.launch(Manifest.permission.READ_CONTACTS)"))
        assertTrue(activity.contains("Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS"))
    }

    @Test fun `vor dem Senden sind Vorschau Anzahl und Herkunft sichtbar`() {
        val gesendet = mutableListOf<Pair<String, JsonObject>>()
        val ablauf = KontaktImportAblauf { art, inhalt -> gesendet += art to inhalt }
        val vorschau = ablauf.vorschau(KontaktSnapshot(listOf(kontakt()), true), "partner-a", "geraet-a")

        assertEquals(1, vorschau.anzahl)
        assertEquals(KontaktImportHerkunft("com.example", "Privat", "set", 1), vorschau.herkuenfte.single())
        assertTrue(gesendet.isEmpty())
        assertThrows(IllegalStateException::class.java) { ablauf.bestaetigen("falsche-vorschau") }
        assertTrue(gesendet.isEmpty())

        assertEquals(1, ablauf.bestaetigen(vorschau.id))
        assertEquals(listOf("kontakt_import_manifest", "kontakt_import_karte"), gesendet.map { it.first })
        assertEquals(1, gesendet.first().second["anzahl"]!!.jsonPrimitive.content.toInt())
        assertEquals("Privat", gesendet.first().second["herkuenfte"]!!.jsonArray.single().jsonObject["kontoName"]!!.jsonPrimitive.content)
        assertFalse(gesendet.any { (_, inhalt) -> inhalt.toString().contains("loesch", ignoreCase = true) })
    }

    @Test fun `Bindungen sind stabil mit Lookup Fallback und Partner Geraet Namespace`() {
        val ohneSourceA = kontakt(source = "", raw = 1)
        val ohneSourceB = kontakt(source = "", raw = 999)
        val erste = KontaktImportAblauf.bindung("partner-a", "geraet-a", ohneSourceA)
        assertEquals(erste, KontaktImportAblauf.bindung("partner-a", "geraet-a", ohneSourceB))
        assertNotEquals(erste, KontaktImportAblauf.bindung("partner-b", "geraet-a", ohneSourceA))
        assertNotEquals(erste, KontaktImportAblauf.bindung("partner-a", "geraet-b", ohneSourceA))
        assertNotEquals(erste, KontaktImportAblauf.bindung("partner-a", "geraet-a", kontakt("source-2")))
        assertTrue(erste.matches(Regex("urn:magnolie:import:android:[0-9a-f]{64}")))
    }

    @Test fun `Importgrenzen werden vor dem Senden erzwungen`() {
        val ablauf = KontaktImportAblauf { _, _ -> error("darf nicht senden") }
        val zuViele = List(KontaktImportAblauf.MAX_KONTAKTE + 1) { kontakt(raw = it.toLong()) }
        assertThrows(IllegalArgumentException::class.java) {
            ablauf.vorschau(KontaktSnapshot(zuViele, true), "partner", "geraet")
        }
        assertThrows(IllegalArgumentException::class.java) {
            ablauf.vorschau(KontaktSnapshot(listOf(kontakt()), false), "partner", "geraet")
        }
    }

    @Test fun `Kontakte ohne stabile Kennung werden uebersprungen statt zu kollidieren`() {
        val ohneKennung = kontakt(source = "", lookup = "")
        val gueltig = kontakt(raw = 8)
        val ablauf = KontaktImportAblauf { _, _ -> }
        val gleicheBindung = kontakt(raw = 9)
        val vorschau = ablauf.vorschau(
            KontaktSnapshot(listOf(ohneKennung, gueltig, gleicheBindung), true), "partner", "geraet")
        assertEquals(1, vorschau.anzahl)
        assertThrows(IllegalArgumentException::class.java) {
            KontaktImportAblauf { _, _ -> }.vorschau(KontaktSnapshot(listOf(ohneKennung), true), "partner", "geraet")
        }
    }
}
