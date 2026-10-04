package io.gitlab.maik3531.magnolienotes.ui

import android.text.format.DateFormat
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Checkbox
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.res.stringResource
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import io.gitlab.maik3531.magnolienotes.daten.ZeitDruckTexte
import io.gitlab.maik3531.magnolienotes.daten.ZeitDruckvorlage
import java.time.YearMonth
import java.time.format.DateTimeFormatter

@Composable
internal fun ZeitMonate(stand: ZeiterfassungStand, speichert: Boolean, speichern: ZeitSpeichern,
                        beiPapierkorb: () -> Unit) {
    val context = LocalContext.current
    val locale = context.resources.configuration.locales[0]
    val entries = stand.entries.filterNot { it.deleted }
    val months = entries.map { YearMonth.from(it.localStart()) }.distinct().sortedDescending()
    var selected by rememberSaveable { mutableStateOf((months.firstOrNull() ?: YearMonth.now()).toString()) }
    var menu by remember { mutableStateOf(false) }
    var removal by remember { mutableStateOf<Pair<String, List<Zeiteintrag>>?>(null) }
    var reportName by remember(stand.reportName) { mutableStateOf(stand.reportName) }
    var allDays by rememberSaveable(selected) { mutableStateOf(true) }
    var picked by remember(selected) { mutableStateOf(emptySet<Int>()) }
    val month = YearMonth.parse(selected)
    val formatter = remember(locale) { DateTimeFormatter.ofPattern(DateFormat.getBestDateTimePattern(locale, "yMMMM"), locale) }
    val monthEntries = entries.filter { YearMonth.from(it.localStart()) == month }
    Abschnitt(stringResource(R.string.zeit_erfasste)) {
        Text(stringResource(R.string.zeit_monat))
        Box {
            Papierknopf(formatter.format(month.atDay(1)), aktiv = !speichert) { menu = true }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                (months + month + YearMonth.now()).distinct().sortedDescending().forEach { value ->
                    DropdownMenuItem(text = { Text(formatter.format(value.atDay(1))) },
                        onClick = { selected = value.toString(); menu = false })
                }
            }
        }
        if (monthEntries.isEmpty()) Text(stringResource(R.string.zeit_leer))
        Schreibfeld(reportName, stringResource(R.string.zeit_druck_name), { reportName = it }, aktiv = !speichert)
        Row(Modifier.fillMaxWidth().toggleable(allDays, enabled = !speichert, role = Role.Checkbox,
            onValueChange = { allDays = it }), verticalAlignment = Alignment.CenterVertically) {
            Checkbox(allDays, null, enabled = !speichert)
            Text(stringResource(R.string.zeit_alle_tage))
        }
        if (!allDays) {
            val dayFormat = DateTimeFormatter.ofPattern(DateFormat.getBestDateTimePattern(locale, "EEEyyyyMMdd"), locale)
                .withDecimalStyle(java.time.format.DecimalStyle.of(locale))
            for (day in 1..month.lengthOfMonth()) Row(Modifier.fillMaxWidth().toggleable(day in picked,
                enabled = !speichert, role = Role.Checkbox, onValueChange = { checked ->
                    picked = if (checked) picked + day else picked - day
                }), verticalAlignment = Alignment.CenterVertically) {
                Checkbox(day in picked, null, enabled = !speichert)
                Text(dayFormat.format(month.atDay(day)))
            }
        }
        Lederknopf(stringResource(R.string.zeit_drucken), aktiv = !speichert && (allDays || picked.isNotEmpty())) {
            val chosenName = reportName
            val days = if (allDays) (1..month.lengthOfMonth()).toSet() else picked.toSet()
            val labels = ZeitDruckTexte(context.getString(R.string.zeit_titel), context.getString(R.string.zeit_druck_name),
                context.getString(R.string.zeit_druck_datum), context.getString(R.string.zeit_druck_unterschrift),
                context.getString(R.string.zeit_druck_summe), context.getString(R.string.zeit_druck_uhrzeit),
                listOf(R.string.zeit_druck_datum, R.string.zeit_art, R.string.zeit_beginn, R.string.zeit_druck_enddatum,
                    R.string.zeit_ende, R.string.zeit_druck_stunden, R.string.zeit_pause, R.string.zeit_gesamt,
                    R.string.baum_kontakt_notiz, R.string.zeit_druck_zeitumstellung).map { context.getString(it) })
            fun error() = android.widget.Toast.makeText(context, R.string.zeit_druck_fehler, android.widget.Toast.LENGTH_LONG).show()
            val document = runCatching { ZeitDruckvorlage.html(month, days, entries, chosenName, stand.calendar,
                labels, locale, DateFormat.is24HourFormat(context)) }.getOrNull()
            if (document == null) error() else speichern({ it.copy(reportName = chosenName) }, {
                runCatching { ZeitDrucken.starten(context, document, labels.title + " " + month) { error() } }
                    .onFailure { error() }
            })
        }
        Papierknopf(stringResource(R.string.zeit_monat_entfernen), aktiv = !speichert && monthEntries.isNotEmpty()) {
            removal = selected to monthEntries.toList()
        }
        Papierknopf(stringResource(R.string.papierkorb_titel), beiKlick = beiPapierkorb)
    }
    removal?.let { (key, snapshot) ->
        AlertDialog(onDismissRequest = { if (!speichert) removal = null },
            title = { Text(formatter.format(YearMonth.parse(key).atDay(1))) },
            text = { Text(stringResource(R.string.zeit_monat_entfernen_frage)) },
            confirmButton = { TextButton(enabled = !speichert, onClick = {
                speichern({ it.removeLocal(snapshot, month = key) }, { removal = null })
            }) { Text(stringResource(R.string.loeschen)) } },
            dismissButton = { TextButton(enabled = !speichert, onClick = { removal = null }) { Text(stringResource(R.string.abbrechen)) } })
    }
}
