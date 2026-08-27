package io.gitlab.maik3531.magnolienotes.ui

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TelefonLayoutTest {
    private val root = File(requireNotNull(System.getProperty("user.dir")))

    @Test fun `Telefonverbindung folgt der vorgesehenen Reihenfolge`() {
        val source = File(root,
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/BaumBlatt.kt").readText()
        val markers = listOf(
            "R.string.telefon_hauptschalter",
            "telefon.found.forEach",
            "R.string.telefon_bluetooth_systempaarung",
            "R.string.telefon_bluetooth_fallback",
            "R.string.telefon_benachrichtigungen_titel",
            "R.string.telefon_systemzugriff_erteilt",
            "R.string.telefon_apps_titel",
            "R.string.telefon_eingehend_titel",
            "R.string.telefon_waehlen_schalter",
            "R.string.telefon_eingehend_schalter",
            "R.string.telefon_nummer_schalter",
            "R.string.telefon_annehmen_schalter"
        )
        val positions = markers.map(source::indexOf)
        assertTrue("Telefonabschnitte fehlen", positions.all { it >= 0 })
        assertTrue("Telefonabschnitte sind falsch angeordnet", positions.zipWithNext().all { it.first < it.second })
        assertTrue(source.indexOf("telefon.peer?.let") < source.indexOf("R.string.telefon_entkoppeln"))
        assertFalse(source.contains("telefon_benachrichtigungen_schalter"))
        assertFalse(source.contains("beiBenachrichtigungen"))
    }

    @Test fun `Trenner und Papierkorb liegen im richtigen Blatt`() {
        val tree = File(root,
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/BaumBlatt.kt").readText()
        val journal = File(root,
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/ui/JournalBlatt.kt").readText()
        assertTrue(tree.indexOf("R.string.personal_sync_titel") < tree.indexOf(".height(1.dp).background(Magnolie.braun)"))
        assertTrue(tree.indexOf(".height(1.dp).background(Magnolie.braun)") < tree.indexOf("R.string.baum_ueberschrift"))
        assertFalse(tree.contains("R.string.papierkorb_titel"))
        assertTrue(journal.indexOf("R.string.papierkorb_titel") < journal.indexOf("R.string.journal_titel"))
        assertTrue(journal.contains("R.string.papierkorb_hinweis"))
    }

    @Test fun `Dienst startet die Geraetesuche ohne manuelle Aktion`() {
        val source = File(root,
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/telefon/TelefonWerk.kt").readText()
        assertTrue(source.contains("if (safePeer() == null) thread(name = \"magnolie-phone-discovery\""))
        assertTrue(source.contains("discovering.compareAndSet(false, true)"))
    }
}
