package io.gitlab.maik3531.magnolienotes.ui

import io.gitlab.maik3531.magnolienotes.R
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TechnischeWerteLokalisierungTest {
    @Test fun `alle bekannten Arten sind vollstaendig abgebildet`() {
        val erwartet = mapOf(
            "note" to R.string.technischer_wert_art_notiz,
            "notebook" to R.string.technischer_wert_art_notizbuch,
            "task" to R.string.technischer_wert_art_aufgabe,
            "attachment" to R.string.technischer_wert_art_anhang
        )
        assertEquals(erwartet.keys, TechnischeWerteLokalisierung.bekannteArten)
        assertEquals(erwartet, erwartet.keys.associateWith { TechnischeWerteLokalisierung.art(it).resource })
    }

    @Test fun `alle bekannten Journalgruende sind vollstaendig abgebildet`() {
        val erwartet = mapOf(
            "manual" to R.string.technischer_wert_grund_manuell,
            "scheduled" to R.string.technischer_wert_grund_geplant,
            "pre-restore" to R.string.technischer_wert_grund_vor_wiederherstellung,
            "pre-sync-full" to R.string.technischer_wert_grund_vor_vollabgleich,
            "pre-sync-task" to R.string.technischer_wert_grund_vor_aufgabenabgleich,
            "pre-sync-note" to R.string.technischer_wert_grund_vor_notizabgleich,
            "contact-import" to R.string.technischer_wert_grund_kontaktimport,
            "contact-keep-together" to R.string.technischer_wert_grund_kontakt_zusammenfuehren,
            "contact-delete" to R.string.technischer_wert_grund_kontaktloeschung
        )
        assertEquals(erwartet.keys, TechnischeWerteLokalisierung.bekannteJournalGruende)
        assertEquals(erwartet, erwartet.keys.associateWith { TechnischeWerteLokalisierung.journalGrund(it).resource })
    }

    @Test fun `alle bekannten Journaldomaenen sind vollstaendig abgebildet`() {
        val erwartet = mapOf(
            "android-app-data" to R.string.technischer_wert_domaene_appdaten,
            "android-system-contacts" to R.string.technischer_wert_domaene_systemkontakte
        )
        assertEquals(erwartet.keys, TechnischeWerteLokalisierung.bekannteJournalDomaenen)
        assertEquals(erwartet, erwartet.keys.associateWith { TechnischeWerteLokalisierung.journalDomaene(it).resource })
    }

    @Test fun `bekannte Journalzusammenfassungen werden strukturiert abgebildet`() {
        assertEquals(LokalisierterTechnischerWert(R.plurals.technischer_wert_zusammenfassung_app, 3, listOf(3, 2)),
            TechnischeWerteLokalisierung.journalZusammenfassung("3 notes, 2 tasks"))
        assertEquals(LokalisierterTechnischerWert(R.plurals.technischer_wert_zusammenfassung_kontakte, 4, listOf(4)),
            TechnischeWerteLokalisierung.journalZusammenfassung("4 contact(s)"))
        assertEquals(LokalisierterTechnischerWert(R.plurals.technischer_wert_zusammenfassung_kontakte_mit_namen,
            2, listOf(2, "Ada, Linus")), TechnischeWerteLokalisierung.journalZusammenfassung(
            "2 contact(s): Ada, Linus"))
    }

    @Test fun `unbekannte Werte nutzen sicheren fachlichen Fallback`() {
        assertEquals(R.string.technischer_wert_art_unbekannt,
            TechnischeWerteLokalisierung.art("future-kind").resource)
        assertEquals(R.string.technischer_wert_grund_unbekannt,
            TechnischeWerteLokalisierung.journalGrund("future-reason").resource)
        assertEquals(R.string.technischer_wert_domaene_unbekannt,
            TechnischeWerteLokalisierung.journalDomaene("future-domain").resource)
        val fallback = TechnischeWerteLokalisierung.journalZusammenfassung("future\nsummary" + "x".repeat(100))
        assertEquals(R.string.technischer_wert_zusammenfassung_unbekannt, fallback.resource)
        val sichtbar = fallback.argumente.single() as String
        assertTrue('\n' !in sichtbar)
        assertEquals(80, sichtbar.length)
    }
}
