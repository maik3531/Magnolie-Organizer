package io.gitlab.maik3531.magnolienotes.ui

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.*
import org.junit.Test

class PapierkorbVerkabelungTest {
    private val root = File("app/src/main")
    private fun source(name: String) = File(root, "java/io/gitlab/maik3531/magnolienotes/$name.kt").readText()

    @Test fun allTwentyLocalesHaveExplicitTrashAndPermanentLocalRemovalQuestions() {
        val files = File(root, "res").listFiles()!!.map { File(it, "trash.xml") }.filter { it.isFile }
        assertEquals(20, files.size)
        for (file in files) {
            val document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file)
            val strings = document.getElementsByTagName("string")
            val values = (0 until strings.length).associate {
                val node = strings.item(it)
                node.attributes.getNamedItem("name").nodeValue to node.textContent
            }
            assertEquals(setOf("loeschen_papierkorb_frage", "loeschen_endgueltig_frage", "loeschen_nur_lokal"), values.keys)
            assertTrue(values.values.all { it.isNotBlank() && !it.contains("30") })
            assertNotEquals(values["loeschen_papierkorb_frage"], values["loeschen_endgueltig_frage"])
            assertTrue(values.getValue("loeschen_nur_lokal").contains("Organizer"))
        }
    }

    @Test fun confirmationBindsTheReviewedMixedSelectionAndDoesNotUseLegacyTimeExpiry() {
        val ui = source("ui/JournalBlatt")
        assertTrue(ui.contains("papierkorbLeeren = PapierkorbLogik.kennungen(papierkorb)"))
        assertTrue(ui.contains("auswahl.size, auswahl.size"))
        assertTrue(ui.contains("handlungen.beiPapierkorbLeeren(auswahl)"))
        assertTrue(ui.contains("sortedWith(compareByDescending<GemeinsamerPapierkorbeintrag>"))
        assertFalse(ui.contains("expiresMs"))
        assertTrue(ui.contains("if (papierkorbAn)"))
        val main = source("MainActivity")
        assertTrue(main.contains("zeitAktion({ ablage.papierkorbLeeren(auswahl) })"))
        assertTrue(main.contains("ablage.entferneZeitenLokal(eintraege, monat, einstellung)"))
        assertTrue(main.contains("ablage.zeitPapierkorbWiederherstellen(id)"))
        assertFalse(main.contains("it.purgeExpired()"))
        assertFalse(main.contains("it.removeLocal("))
    }

    @Test fun disabledTrashQuestionNamesThePolicyWithoutRedundantRestorationScope() {
        val files = File(root, "res").listFiles()!!.map { File(it, "trash.xml") }.filter { it.isFile }
        for (file in files) {
            val strings = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file).getElementsByTagName("string")
            val value = (0 until strings.length).map { strings.item(it) }
                .single { it.attributes.getNamedItem("name").nodeValue == "loeschen_endgueltig_frage" }.textContent
            assertTrue(file.path, value.contains(':') || value.contains('：'))
            if (file.parentFile.name == "values-de") assertEquals(
                "Papierkorb deaktiviert: Die ausgewählten Einträge endgültig löschen?", value)
            if (file.parentFile.name == "values") assertEquals(
                "Trash disabled: Permanently delete the selected items?", value)
        }
    }
}
