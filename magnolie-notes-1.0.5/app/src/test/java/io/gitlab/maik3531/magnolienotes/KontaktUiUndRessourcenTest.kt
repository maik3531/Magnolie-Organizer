package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class KontaktUiUndRessourcenTest {
    @Test fun `alle zwanzig Sprachen haben denselben uebersetzbaren Schluesselsatz`() {
        val res = File("app/src/main/res")
        val dateien = res.listFiles()!!.filter { it.name == "values" || it.name.startsWith("values-") }
            .map { File(it, "strings.xml") }.filter(File::exists)
        assertEquals(20, dateien.size)
        fun schluessel(f: File) = Regex("<string name=\"([^\"]+)\"(?![^>]*translatable=\"false\")")
            .findAll(f.readText()).map { it.groupValues[1] }.toSet()
        val basis = schluessel(File(res, "values/strings.xml"))
        dateien.filterNot { it.path.endsWith("values/strings.xml") }.forEach {
            assertEquals("Ressourcenschlüssel in ${it.parentFile.name}", basis, schluessel(it))
        }
    }

    @Test fun `Kontakt UI verdrahtet Vorschau Batch Einzelwahl und getrennte Gefahr`() {
        val ui = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/BaumBlatt.kt").readText()
        listOf("baum_kontakt_alle_sicheren", "baum_kontakt_alle_ablehnen",
            "baum_kontakt_getrennt_importieren", "baum_kontakt_karten_zusammenfuehren",
            "baum_kontakt_verknuepfen", "baum_verbindung_entfernen_frage").forEach {
            assertTrue("Fehlende UI-Verkabelung $it", ui.contains("R.string.$it"))
        }
        assertFalse("Veralteter neutraler Partner-Entfernen-Knopf", ui.contains("R.string.baum_partner_entfernen"))
    }

    @Test fun `es gibt keine Batch Loeschannahme`() {
        val ui = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/BaumBlatt.kt").readText()
        assertTrue(ui.contains("v.art == \"loeschen\""))
        assertTrue(ui.contains("baum_einzeln_bestaetigen"))
        assertFalse(ui.contains("baum_kontakt_alle_loesch"))
    }
}
