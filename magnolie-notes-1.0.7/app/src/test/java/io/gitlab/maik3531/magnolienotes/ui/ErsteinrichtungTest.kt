package io.gitlab.maik3531.magnolienotes.ui

import io.gitlab.maik3531.magnolienotes.Ersteinrichtung
import io.gitlab.maik3531.magnolienotes.R
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ErsteinrichtungTest {
    @Test fun `alle Funktionsgruppen werden in Hauptreihenfolge angeboten`() {
        assertEquals(listOf(R.string.blatt_notizen, R.string.blatt_aufgaben,
            R.string.blatt_einfuhr, R.string.blatt_baum, R.string.blatt_journal),
            Ersteinrichtung.schritte.map { it.titel })
        assertTrue(Ersteinrichtung.schritte[3].texte.containsAll(listOf(
            R.string.telefon_hinweis, R.string.personal_sync_hinweis, R.string.baum_erklaerung)))
        assertTrue(Ersteinrichtung.schritte[4].texte.containsAll(listOf(
            R.string.papierkorb_hinweis, R.string.journal_hinweis)))
    }
}
