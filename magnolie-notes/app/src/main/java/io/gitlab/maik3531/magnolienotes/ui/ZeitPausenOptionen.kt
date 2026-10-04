package io.gitlab.maik3531.magnolienotes.ui

import android.app.TimePickerDialog
import android.text.format.DateFormat
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.ZeitPausenfenster
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import java.util.Calendar
import java.util.TimeZone

@Composable
fun ZeitPausenOptionen(stand: ZeiterfassungStand, speichert: Boolean, speichern: ZeitSpeichern) {
    val context = LocalContext.current
    var edit by rememberSaveable { mutableStateOf<Int?>(null) }
    var start by rememberSaveable { mutableStateOf(720) }
    var end by rememberSaveable { mutableStateOf(750) }
    // Retain the exact rule list across recomposition and configuration changes for compare-and-save.
    var expected by rememberSaveable { mutableStateOf(emptyList<Int>()) }
    fun time(minute: Int): String {
        val zone = TimeZone.getTimeZone("UTC")
        val date = Calendar.getInstance(zone).apply {
            clear(); set(2026, Calendar.JANUARY, 1, minute / 60, minute % 60)
        }.time
        return DateFormat.getTimeFormat(context).apply { timeZone = zone }.format(date)
    }
    fun open(index: Int) {
        expected = stand.fixedPauses.flatMap { listOf(it.start, it.end) }
        start = stand.fixedPauses.getOrNull(index)?.start ?: 720
        end = stand.fixedPauses.getOrNull(index)?.end ?: 750
        edit = index
    }
    fun save(remove: Boolean) {
        val index = edit ?: return
        val before = expected.chunked(2).map { ZeitPausenfenster(it[0], it[1]) }
        val after = before.toMutableList()
        if (remove) after.removeAt(index)
        else if (index < after.size) after[index] = ZeitPausenfenster(start, end)
        else after += ZeitPausenfenster(start, end)
        speichern({ current ->
            check(current.fixedPauses == before)
            current.copy(fixedPauses = after.distinct()).validate()
        }, { edit = null })
    }
    Abschnitt(stringResource(R.string.zeit_feste_pausen)) {
        Text(stringResource(R.string.zeit_pausen_neustart))
        stand.fixedPauses.forEachIndexed { index, window ->
            Papierknopf("${time(window.start)} – ${time(window.end)}", aktiv = !speichert) { open(index) }
        }
        Papierknopf(stringResource(R.string.zeit_feste_pause_neu), aktiv = !speichert && stand.fixedPauses.size < 16) {
            open(stand.fixedPauses.size)
        }
    }
    if (edit != null) AlertDialog(onDismissRequest = { if (!speichert) edit = null },
        title = { Text(stringResource(R.string.zeit_feste_pausen)) },
        text = { Column {
            Row(Modifier.fillMaxWidth()) {
                Papierknopf(stringResource(R.string.zeit_beginn) + ": " + time(start),
                    modifier = Modifier.weight(1f), aktiv = !speichert) {
                    TimePickerDialog(context, { _, hour, minute -> start = hour * 60 + minute },
                        start / 60, start % 60, DateFormat.is24HourFormat(context)).show()
                }
                Papierknopf(stringResource(R.string.zeit_ende) + ": " + time(end),
                    modifier = Modifier.weight(1f), aktiv = !speichert) {
                    TimePickerDialog(context, { _, hour, minute -> end = hour * 60 + minute },
                        end / 60, end % 60, DateFormat.is24HourFormat(context)).show()
                }
            }
            if (edit!! < expected.size / 2) Papierknopf(stringResource(R.string.loeschen), aktiv = !speichert) { save(true) }
        } },
        confirmButton = { TextButton(enabled = !speichert && start != end, onClick = { save(false) }) {
            Text(stringResource(R.string.sichern))
        } },
        dismissButton = { TextButton(enabled = !speichert, onClick = { edit = null }) { Text(stringResource(R.string.abbrechen)) } })
}
