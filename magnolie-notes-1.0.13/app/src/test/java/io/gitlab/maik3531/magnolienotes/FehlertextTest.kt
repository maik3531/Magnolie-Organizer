package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class FehlertextTest {
    @Test
    fun `bekannte technische Fehler haben lokalisierte Ressourcen`() {
        assertEquals(
            R.string.fehler_paarungsdatei_abgelaufen,
            Fehlertext.ressourcenId("Die Paarungsdatei gilt nicht mehr.")
        )
        assertEquals(
            R.string.fehler_bluetooth_berechtigung,
            Fehlertext.ressourcenId("Die Bluetooth-Berechtigung fehlt.")
        )
        assertEquals(
            R.string.fehler_datei_oeffnen,
            Fehlertext.ressourcenId(Fehlertext.DATEI_OEFFNEN)
        )
    }

    @Test
    fun `unbekannte oder leere Fehler zeigen immer den allgemeinen Text`() {
        assertEquals(R.string.fehler_allgemein, Fehlertext.ressourcenId(null))
        assertEquals(R.string.fehler_allgemein, Fehlertext.ressourcenId(""))
        assertEquals(R.string.fehler_allgemein, Fehlertext.ressourcenId("interner Fehler"))
    }

    @Test
    fun `sichtbare Kotlin Grenzen enthalten keine entfernten deutschen Literale`() {
        val wurzel = File("app/src/main/java/io/gitlab/maik3531/magnolienotes")
        val grenzen = listOf(
            "MainActivity.kt",
            "ui/BaumBlatt.kt",
            "ui/NotizBlatt.kt",
            "ui/AufgabenBlatt.kt",
            "ui/Symbole.kt"
        ).map { File(wurzel, it).readText() }.joinToString("\n")
        listOf(
            "Eigene Paarungsdatei erzeugen", "Paarungsdatei weitergeben",
            "Vergleiche den Code", "Verbinden", "Code stimmt", "Zuletzt geschehen",
            "bestätigt", "wartet", "Lose Notizen", "Geteilt", "Übernommen"
        ).forEach { assertFalse("UI-Literal nicht extrahiert: $it", grenzen.contains("\"$it")) }
    }

    @Test
    fun `default und deutsch enthalten alle neuen Schluessel`() {
        fun schluessel(pfad: String): Set<String> = Regex("<string name=\"([^\"]+)\"")
            .findAll(File(pfad).readText()).map { it.groupValues[1] }.toSet()
        val standard = schluessel("app/src/main/res/values/strings.xml")
        val deutsch = schluessel("app/src/main/res/values-de/strings.xml")
        val erforderlich = setOf(
            "notizbuch_standard", "herkunft_geteilt", "herkunft_uebernommen",
            "baum_code_vergleichen", "baum_ereignisse", "fehler_allgemein",
            "symbol_einkauf", "symbol_notiz", "aufgabe_vorlauf_erhoehen", "aufgabe_ohne_kopf"
        )
        assertTrue(standard.containsAll(erforderlich))
        assertTrue(deutsch.containsAll(erforderlich))
    }
}
