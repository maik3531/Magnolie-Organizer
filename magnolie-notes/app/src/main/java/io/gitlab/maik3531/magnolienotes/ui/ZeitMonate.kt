package io.gitlab.maik3531.magnolienotes.ui

import android.text.format.DateFormat
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.res.stringResource
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.PapierkorbEinstellungen
import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import java.time.YearMonth
import java.time.format.DateTimeFormatter

@Composable
internal fun ZeitMonate(stand: ZeiterfassungStand, speichert: Boolean, speichern: ZeitSpeichern,
                        beiPapierkorb: () -> Unit,
                        papierkorb: PapierkorbEinstellungen = PapierkorbEinstellungen(),
                        beiEntfernen: ZeitEntfernen? = null,
                        beiDruckAuswahl: (ZeitMonatsDruckAuswahl?) -> Unit = {}) {
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
    val druckAuswahl = ZeitMonatsDruckAuswahl(month,
        if (allDays) (1..month.lengthOfMonth()).toSet() else picked.toSet(), reportName)
    val aktuelleDruckAuswahl by androidx.compose.runtime.rememberUpdatedState(beiDruckAuswahl)
    androidx.compose.runtime.SideEffect { aktuelleDruckAuswahl(druckAuswahl) }
    androidx.compose.runtime.DisposableEffect(Unit) {
        onDispose { aktuelleDruckAuswahl(null) }
    }
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
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Papierknopf(stringResource(R.string.zeit_monat_entfernen), aktiv = !speichert && monthEntries.isNotEmpty(), destruktiv = true) {
                removal = selected to monthEntries.toList()
            }
            if (papierkorb.an) Papierknopf(stringResource(R.string.papierkorb_titel), beiKlick = beiPapierkorb)
        }
    }
    removal?.let { (key, snapshot) ->
        AlertDialog(onDismissRequest = { if (!speichert) removal = null }, containerColor = Magnolie.papier,
            title = { Text(formatter.format(YearMonth.parse(key).atDay(1))) },
            text = { Text(loeschHinweis(papierkorb.an, lokal = true)) },
            confirmButton = { TextButton(enabled = !speichert, onClick = {
                if (beiEntfernen != null) beiEntfernen(snapshot, key, papierkorb) { removal = null }
                else speichern({ it.removeLocal(snapshot, month = key, papierkorb = papierkorb) }, { removal = null })
            }) { Text(stringResource(R.string.loeschen), color = Magnolie.rot) } },
            dismissButton = { TextButton(enabled = !speichert, onClick = { removal = null }) { Text(stringResource(R.string.abbrechen), color = Magnolie.braun) } })
    }
}
