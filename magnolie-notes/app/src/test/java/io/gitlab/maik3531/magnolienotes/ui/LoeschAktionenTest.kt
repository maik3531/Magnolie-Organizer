package io.gitlab.maik3531.magnolienotes.ui

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class LoeschAktionenTest {
    private val root = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/ui")
    private val labels = setOf("loeschen", "papierkorb_endgueltig_titel", "papierkorb_leeren", "zeit_monat_entfernen",
        "personal_sync_alle_loeschen", "telefon_entkoppeln", "baum_verbindung_entfernen")

    private fun paperCalls(text: String): List<String> = Regex("\\bPapierknopf\\(").findAll(text).map { start ->
        var depth = 1; var index = start.range.last + 1; var quoted = false; var escaped = false
        while (index < text.length && depth > 0) {
            val value = text[index++]
            if (quoted) { if (escaped) escaped = false else if (value == '\\') escaped = true else if (value == '"') quoted = false }
            else when (value) { '"' -> quoted = true; '(' -> depth++; ')' -> depth-- }
        }
        text.substring(start.range.first, index)
    }.toList()

    @Test fun allDeleteRemoveAndEmptyTrashButtonsExplicitlyUseTheRedDestructiveStyle() {
        var checked = 0
        root.listFiles()!!.filter { it.extension == "kt" }.forEach { file ->
            paperCalls(file.readText()).forEach { call ->
                if (labels.any { call.contains("R.string.$it") }) {
                    assertTrue(file.name + ": " + call, call.contains("destruktiv = true"))
                    checked++
                }
            }
        }
        assertTrue("The audit must cover editors, trash, recovery, time and connection actions", checked >= 13)
    }

    @Test fun dynamicSwipeAndConflictDeleteChoicesAreRedButOtherActionsKeepTheirNormalColors() {
        val swipe = File(root, "EintragsWischen.kt").readText()
        for (value in listOf("action", "value.links", "value.rechts"))
            assertTrue(swipe.contains("destruktiv = $value == WischAktion.LOESCHEN"))
        val conflict = File(root, "ZeitKonflikt.kt").readText()
        assertTrue(conflict.contains("Text(choice, color = if (entry.deleted) Magnolie.rot else androidx.compose.ui.graphics.Color.Unspecified)"))
        val tree = File(root, "BaumBlatt.kt").readText().substringAfter("private fun Papierkorbknopf(").substringBefore("\n@Composable")
        assertFalse(tree.contains("Magnolie.braun"))
        assertTrue(Regex("Magnolie.rot").findAll(tree).count() >= 5)
    }

    @Test fun trashNavigationAndRestoreCancelActionsAreNotMistakenForDeletion() {
        val journal = File(root, "JournalBlatt.kt").readText()
        val neutral = paperCalls(journal).filter { it.contains("R.string.journal_restore") || it.contains("R.string.baum_annehmen") }
        assertTrue(neutral.isNotEmpty())
        neutral.forEach { assertFalse(it.contains("destruktiv = true")) }
    }
}
