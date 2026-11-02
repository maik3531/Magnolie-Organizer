package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import android.text.format.DateFormat
import android.widget.Toast
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.ZeitDruckTexte
import io.gitlab.maik3531.magnolienotes.daten.ZeitDruckvorlage
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import java.time.YearMonth

/** Only the visible selection is hoisted; no book snapshot or composable callback is retained. */
data class ZeitMonatsDruckAuswahl(val monat: YearMonth, val tage: Set<Int>, val name: String)

internal fun zeitMonatDrucken(context: Context, stand: ZeiterfassungStand,
                             auswahl: ZeitMonatsDruckAuswahl, speichern: ZeitSpeichern) {
    val locale = context.resources.configuration.locales[0]
    val labels = ZeitDruckTexte(context.getString(R.string.zeit_titel), context.getString(R.string.zeit_druck_name),
        context.getString(R.string.zeit_druck_datum), context.getString(R.string.zeit_druck_unterschrift),
        context.getString(R.string.zeit_druck_summe), context.getString(R.string.zeit_druck_uhrzeit),
        listOf(R.string.zeit_druck_datum, R.string.zeit_art, R.string.zeit_beginn, R.string.zeit_druck_enddatum,
            R.string.zeit_ende, R.string.zeit_druck_stunden, R.string.zeit_pause, R.string.zeit_gesamt,
            R.string.baum_kontakt_notiz, R.string.zeit_druck_zeitumstellung).map { context.getString(it) })
    fun error() = Toast.makeText(context, R.string.zeit_druck_fehler, Toast.LENGTH_LONG).show()
    val document = runCatching { ZeitDruckvorlage.html(auswahl.monat, auswahl.tage,
        stand.entries.filterNot { it.deleted }, auswahl.name, stand.calendar,
        labels, locale, DateFormat.is24HourFormat(context)) }.getOrNull()
    if (document == null) error() else speichern({ it.copy(reportName = auswahl.name) }, {
        runCatching { ZeitDrucken.starten(context, document, labels.title + " " + auswahl.monat) { error() } }
            .onFailure { error() }
    })
}
