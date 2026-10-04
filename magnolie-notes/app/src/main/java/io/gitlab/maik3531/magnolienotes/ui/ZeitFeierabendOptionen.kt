package io.gitlab.maik3531.magnolienotes.ui

import android.app.TimePickerDialog
import android.text.format.DateFormat
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.ZeitEntwurf
import io.gitlab.maik3531.magnolienotes.daten.ZeitFeierabendwecker
import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand

@Composable
fun ZeitFeierabendOptionen(stand: ZeiterfassungStand, speichert: Boolean, speichern: ZeitSpeichern) {
    val context = LocalContext.current
    val original = stand.endAlarm
    val locale = context.resources.configuration.locales[0]
    var enabled by rememberSaveable(original) { mutableStateOf(original.clockMinute != null || original.workedMinutes != null) }
    var clockMode by rememberSaveable(original) { mutableStateOf(original.clockMinute != null) }
    var clock by rememberSaveable(original) { mutableStateOf(original.clockMinute ?: 960) }
    var duration by rememberSaveable(original) { mutableStateOf(Zeiteintrag.duration(original.workedMinutes ?: 480, locale)) }
    var includePauses by rememberSaveable(original) { mutableStateOf(original.includePauses) }
    var autoStop by rememberSaveable(original) { mutableStateOf(original.autoStop) }
    val minutes = runCatching {
        val parts = Regex("([0-9]+):([0-5][0-9])").matchEntire(ZeitEntwurf.digits(duration).trim()) ?: error("duration")
        Math.addExact(Math.multiplyExact(parts.groupValues[1].toLong(), 60), parts.groupValues[2].toLong())
    }.getOrNull()
    val candidate = runCatching {
        if (enabled && !clockMode) require(minutes != null)
        ZeitFeierabendwecker(clockMinute = clock.takeIf { enabled && clockMode },
            workedMinutes = minutes.takeIf { enabled && !clockMode }, includePauses = includePauses,
            autoStop = enabled && autoStop).validate()
    }.getOrNull()
    @Composable fun toggle(label: String, value: Boolean, change: (Boolean) -> Unit) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, modifier = Modifier.weight(1f))
            Switch(checked = value, enabled = !speichert, onCheckedChange = change,
                modifier = Modifier.semantics { contentDescription = label })
        }
    }
    Abschnitt(stringResource(R.string.zeit_feierabend)) {
        Text(stringResource(R.string.zeit_pausen_neustart))
        toggle(stringResource(R.string.aufgabe_erinnern), enabled) { enabled = it }
        if (enabled) {
            Row(Modifier.fillMaxWidth()) {
                Papierknopf(stringResource(R.string.zeit_druck_uhrzeit), modifier = Modifier.weight(1f),
                    aktiv = !speichert, ausgewaehlt = clockMode) { clockMode = true }
                Papierknopf(stringResource(R.string.zeit_druck_stunden), modifier = Modifier.weight(1f),
                    aktiv = !speichert, ausgewaehlt = !clockMode) { clockMode = false }
            }
            if (clockMode) {
                Papierknopf(Zeit.erinnerungsUhrzeit(context, clock), aktiv = !speichert) {
                    TimePickerDialog(context, { _, hour, minute -> clock = hour * 60 + minute },
                        clock / 60, clock % 60, DateFormat.is24HourFormat(context)).show()
                }
            } else {
                Schreibfeld(duration, stringResource(R.string.zeit_gesamt), { duration = it }, aktiv = !speichert)
                toggle(stringResource(R.string.zeit_pausen_einrechnen), includePauses) { includePauses = it }
            }
            toggle(stringResource(R.string.zeit_automatisch_beenden), autoStop) { autoStop = it }
        }
        Papierknopf(stringResource(R.string.sichern), aktiv = !speichert && candidate != null && candidate != original) {
            val replacement = candidate ?: return@Papierknopf
            speichern({ state -> check(state.endAlarm == original); state.copy(endAlarm = replacement).validate() }, {})
        }
    }
}
