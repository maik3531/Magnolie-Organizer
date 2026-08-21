package io.gitlab.maik3531.magnolienotes.ui

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import io.gitlab.maik3531.magnolienotes.R

internal data class LokalisierterTechnischerWert(
    val resource: Int,
    val menge: Int? = null,
    val argumente: List<Any> = emptyList()
)

/** Zentrale Grenze zwischen gespeicherten Protokollwerten und nutzersichtbaren Texten. */
internal object TechnischeWerteLokalisierung {
    val bekannteArten = setOf("note", "notebook", "task", "attachment")
    val bekannteJournalGruende = setOf(
        "manual", "scheduled", "pre-restore", "pre-sync-full", "pre-sync-task", "pre-sync-note",
        "contact-import", "contact-keep-together", "contact-delete"
    )
    val bekannteJournalDomaenen = setOf("android-app-data", "android-system-contacts")

    fun art(wert: String) = when (wert) {
        "note" -> text(R.string.technischer_wert_art_notiz)
        "notebook" -> text(R.string.technischer_wert_art_notizbuch)
        "task" -> text(R.string.technischer_wert_art_aufgabe)
        "attachment" -> text(R.string.technischer_wert_art_anhang)
        else -> unbekannt(R.string.technischer_wert_art_unbekannt, wert)
    }

    fun journalGrund(wert: String) = when (wert) {
        "manual" -> text(R.string.technischer_wert_grund_manuell)
        "scheduled" -> text(R.string.technischer_wert_grund_geplant)
        "pre-restore" -> text(R.string.technischer_wert_grund_vor_wiederherstellung)
        "pre-sync-full" -> text(R.string.technischer_wert_grund_vor_vollabgleich)
        "pre-sync-task" -> text(R.string.technischer_wert_grund_vor_aufgabenabgleich)
        "pre-sync-note" -> text(R.string.technischer_wert_grund_vor_notizabgleich)
        "contact-import" -> text(R.string.technischer_wert_grund_kontaktimport)
        "contact-keep-together" -> text(R.string.technischer_wert_grund_kontakt_zusammenfuehren)
        "contact-delete" -> text(R.string.technischer_wert_grund_kontaktloeschung)
        else -> unbekannt(R.string.technischer_wert_grund_unbekannt, wert)
    }

    fun journalDomaene(wert: String) = when (wert) {
        "android-app-data" -> text(R.string.technischer_wert_domaene_appdaten)
        "android-system-contacts" -> text(R.string.technischer_wert_domaene_systemkontakte)
        else -> unbekannt(R.string.technischer_wert_domaene_unbekannt, wert)
    }

    fun journalZusammenfassung(wert: String): LokalisierterTechnischerWert {
        APP_ZUSAMMENFASSUNG.matchEntire(wert)?.let { treffer ->
            val notizen = treffer.groupValues[1].toIntOrNull()
            val aufgaben = treffer.groupValues[2].toIntOrNull()
            if (notizen != null && aufgaben != null) {
                return plural(R.plurals.technischer_wert_zusammenfassung_app, notizen, notizen, aufgaben)
            }
        }
        KONTAKT_ZUSAMMENFASSUNG.matchEntire(wert)?.let { treffer ->
            val anzahl = treffer.groupValues[1].toIntOrNull()
            if (anzahl != null) {
                val namen = treffer.groupValues[2]
                return if (namen.isBlank()) plural(
                    R.plurals.technischer_wert_zusammenfassung_kontakte, anzahl, anzahl
                ) else plural(
                    R.plurals.technischer_wert_zusammenfassung_kontakte_mit_namen,
                    anzahl, anzahl, namen
                )
            }
        }
        return unbekannt(R.string.technischer_wert_zusammenfassung_unbekannt, wert)
    }

    private fun text(@StringRes resource: Int, vararg argumente: Any) =
        LokalisierterTechnischerWert(resource, argumente = argumente.toList())

    private fun plural(resource: Int, menge: Int, vararg argumente: Any) =
        LokalisierterTechnischerWert(resource, menge, argumente.toList())

    private fun unbekannt(@StringRes resource: Int, wert: String) =
        text(resource, wert.asSequence().filterNot(Char::isISOControl).joinToString("").trim().take(80)
            .ifBlank { "?" })

    private val APP_ZUSAMMENFASSUNG = Regex("(\\d+) notes, (\\d+) tasks")
    private val KONTAKT_ZUSAMMENFASSUNG = Regex("(\\d+) contact\\(s\\)(?:: (.*))?")
}

@Composable
internal fun lokalisierterText(wert: LokalisierterTechnischerWert): String =
    wert.menge?.let {
        pluralStringResource(wert.resource, it, *wert.argumente.toTypedArray())
    } ?: stringResource(wert.resource, *wert.argumente.toTypedArray())
