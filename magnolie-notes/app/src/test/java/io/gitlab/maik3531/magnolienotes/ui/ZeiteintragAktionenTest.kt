package io.gitlab.maik3531.magnolienotes.ui

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class ZeiteintragAktionenTest {
    private fun source(name: String) = File("app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/$name.kt").readText()

    @Test fun editAndManualEntryShareOneHorizontalActionRowWithUnchangedSaveAndDeleteGuards() {
        val actions = source("ZeiteintragAktionen")
        assertEquals(1, Regex("\\bRow\\(").findAll(actions).count())
        assertTrue(actions.contains("horizontalScroll(rememberScrollState())"))
        assertTrue(actions.contains("Arrangement.spacedBy(8.dp)"))
        assertTrue(actions.indexOf("R.string.sichern") < actions.indexOf("R.string.abbrechen"))
        assertTrue(actions.indexOf("R.string.abbrechen") < actions.indexOf("R.string.loeschen"))
        assertTrue(actions.contains("if (!neu) Papierknopf"))
        assertEquals(3, Regex("aktiv = !speichert").findAll(actions).count())
        assertTrue(actions.contains("destruktiv = true, beiKlick = beiLoeschen"))
        val editor = source("ZeiterfassungBlatt").substringAfter("fun ZeiteintragEditor(")
        assertTrue(editor.contains("ZeiteintragAktionen(entwurf.neu, speichert, beiSichern = {"))
        assertTrue(editor.contains("val latest = aktuell()"))
        assertTrue(editor.contains("if (replacement == null) invalid = true"))
        assertTrue(editor.contains("beiLoeschen = { loeschen = true }"))
        assertTrue(editor.contains("if (loeschen) AlertDialog"))
        assertTrue(editor.contains("Text(stringResource(R.string.loeschen), color = Magnolie.rot)"))
    }

    @Test fun destructiveLabelsAlwaysStayRedIncludingDisabledAndSelectedStates() {
        for (active in listOf(false, true)) for (selected in listOf(false, true))
            assertEquals(Magnolie.rot, papierknopfSchriftfarbe(active, selected, destruktiv = true))
    }

    @Test fun existingNonDestructiveButtonColorsRemainUnchanged() {
        assertEquals(Magnolie.braun, papierknopfSchriftfarbe(true, false))
        assertEquals(Magnolie.gold, papierknopfSchriftfarbe(true, true))
        assertEquals(Magnolie.braunHell, papierknopfSchriftfarbe(false, false))
        assertEquals(Magnolie.braunHell, papierknopfSchriftfarbe(false, true))
    }
}
