package io.gitlab.maik3531.magnolienotes.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.text.format.DateFormat
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.TextButton
import androidx.compose.material3.Switch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.Role
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeitEntwurf
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.Date
import java.util.TimeZone
import java.util.UUID
import kotlinx.coroutines.delay

typealias ZeitSpeichern = ((ZeiterfassungStand) -> ZeiterfassungStand, () -> Unit) -> Unit

@Composable
fun ZeiterfassungBlatt(stand: ZeiterfassungStand, speichert: Boolean, speichern: ZeitSpeichern,
                      ansicht: String, beiAnsicht: (String) -> Unit, beiAktiv: (Boolean) -> Unit,
                      beiPapierkorb: () -> Unit,
                      beiBearbeiten: (Zeiteintrag, Boolean) -> Unit) {
    val context = LocalContext.current
    val locale = context.resources.configuration.locales[0]
    var now by remember { mutableStateOf(Zeiteintrag.currentMinute()) }
    var startId by rememberSaveable { mutableStateOf(UUID.randomUUID().toString()) }
    var menuOffen by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            now = Zeiteintrag.currentMinute()
            delay(60000 - System.currentTimeMillis() % 60000)
        }
    }
    val entries = stand.entries.filterNot { it.deleted }
        .sortedWith(compareBy<Zeiteintrag> { it.endMinute != null }.thenByDescending { it.startMinute })
    val current = entries.firstOrNull { it.endMinute == null }
    val suggestion = stringResource(when (Zeiteintrag.suggestedType(
        Instant.ofEpochSecond(now * 60).atZone(ZoneId.systemDefault()).hour)) {
        "early" -> R.string.zeit_frueh
        "late" -> R.string.zeit_spaet
        else -> R.string.zeit_nacht
    })
    val confirm = stringResource(R.string.zeit_bestaetigen)
    @Composable fun karte(entry: Zeiteintrag, bearbeiten: Boolean) {
        val displayed = stand.projected(entry, now)
        Abschnitt(entry.type.ifBlank { context.getString(R.string.zeit_titel) },
            modifier = if (bearbeiten) Modifier.clickable(enabled = !speichert, role = Role.Button) {
                beiBearbeiten(entry, false)
            } else Modifier) {
            val zone = TimeZone.getTimeZone(entry.zone)
            fun time(minute: Long) = DateFormat.getTimeFormat(context).apply { timeZone = zone }.format(Date(minute * 60000))
            fun date(minute: Long) = DateFormat.getDateFormat(context).apply { timeZone = zone }.format(Date(minute * 60000))
            Wertzeile(stringResource(R.string.zeit_beginn), date(entry.startMinute) + " · " + time(entry.startMinute))
            Wertzeile(stringResource(R.string.zeit_ende), entry.endMinute?.let { date(it) + " · " + time(it) }
                ?: stringResource(if (stand.isPaused(entry, now)) R.string.zeit_pause_aktiv else R.string.zeit_laufend))
            Wertzeile(stringResource(R.string.zeit_gesamt), Zeiteintrag.duration(displayed.totalMinutes(now), locale))
            Wertzeile(stringResource(R.string.zeit_pause), java.text.NumberFormat.getIntegerInstance(locale).format(displayed.pausedMinutes(now)))
            if (entry.note.isNotBlank()) Text(entry.note, modifier = Modifier.padding(vertical = 6.dp))
            if (bearbeiten) Papierknopf(stringResource(R.string.zeit_korrektur), aktiv = !speichert) { beiBearbeiten(entry, false) }
        }
    }
    val seiten = listOf("tracking" to R.string.zeit_titel, "settings" to R.string.zeit_optionen,
        "history" to R.string.zeit_erfasste)
    val menueText = stringResource(R.string.zeit_menue)
    Column(Modifier.fillMaxSize().background(Magnolie.papier)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Box {
                TextButton(onClick = { menuOffen = true }, modifier = Modifier.semantics { contentDescription = menueText }) {
                    Text("☰", fontSize = 24.sp, color = Magnolie.braun, modifier = Modifier.clearAndSetSemantics {})
                }
                DropdownMenu(expanded = menuOffen, onDismissRequest = { menuOffen = false }) {
                    seiten.forEach { (key, label) -> DropdownMenuItem(text = { Text(stringResource(label)) },
                        onClick = { menuOffen = false; beiAnsicht(key) }) }
                }
            }
            Text(stringResource(seiten.firstOrNull { it.first == ansicht }?.second ?: R.string.zeit_titel),
                color = Magnolie.braun, fontSize = 18.sp, modifier = Modifier.weight(1f))
        }
        if (ansicht == "settings") {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                ZeiterfassungsOptionen(stand.enabled, speichert, beiAktiv)
                ZeitPausenOptionen(stand, speichert, speichern)
                ZeitFeierabendOptionen(stand, speichert, speichern)
                ZeitMonate(stand, speichert, speichern, beiPapierkorb)
            }
        } else if (ansicht == "history") {
            LazyColumn(Modifier.weight(1f)) {
                item { Abschnitt(stringResource(R.string.zeit_erfasste)) {
                    Papierknopf(stringResource(R.string.zeit_neu), aktiv = stand.enabled && !speichert) {
                        val minute = Zeiteintrag.currentMinute()
                        beiBearbeiten(Zeiteintrag(startMinute = minute, endMinute = minute, type = suggestion), true)
                    }
                    if (entries.isEmpty()) Text(stringResource(R.string.zeit_leer))
                } }
                items(entries, key = { it.id }) { entry -> karte(entry, true) }
            }
        } else LazyColumn(Modifier.weight(1f)) {
        item { Abschnitt(stringResource(R.string.zeit_titel)) {
            BestaetigungsSchieber(stringResource(if (current == null) R.string.zeit_starten else R.string.zeit_beenden), confirm,
                "primary:${current?.id ?: startId}:${current?.clock}", !speichert && (current != null || stand.enabled)) {
                if (current == null) {
                    val entry = Zeiteintrag(id = startId, startMinute = Zeiteintrag.currentMinute(), type = suggestion)
                    speichern({ it.start(entry) }, { startId = UUID.randomUUID().toString() })
                } else speichern({ it.finish(current) }, {})
            }
            if (current != null) {
                val paused = stand.isPaused(current, now)
                BestaetigungsSchieber(stringResource(if (paused) R.string.zeit_fortsetzen else R.string.zeit_pausieren),
                    confirm, "${current.id}:${current.clock}:pause", !speichert) {
                    speichern({ if (paused) it.resume(current) else it.pause(current) }, {})
                }
            }
        } }
        if (current != null) item(key = current.id) { karte(current, false) }
        val pauseAlarm = current?.let { stand.pauseRuns[it.id]?.alarm }
        if (current != null && pauseAlarm != null) item {
            Abschnitt(stringResource(R.string.zeit_pause)) {
                fun select(minutes: Int?) {
                    speichern({ state ->
                        val run = state.pauseRuns[current.id] ?: error("pause ended")
                        check(run.alarm == pauseAlarm)
                        state.copy(pauseRuns = state.pauseRuns + (current.id to run.copy(alarm = pauseAlarm.select(minutes))))
                    }, {})
                }
                val label = stringResource(R.string.aufgabe_erinnern)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(label, modifier = Modifier.weight(1f))
                    Switch(checked = pauseAlarm.minutes != null, enabled = !speichert,
                        onCheckedChange = { select(if (it) 15 else null) },
                        modifier = Modifier.semantics { contentDescription = label })
                }
                if (pauseAlarm.minutes != null) {
                    Row(Modifier.fillMaxWidth()) {
                        io.gitlab.maik3531.magnolienotes.daten.ZeitPausenwecker.CHOICES.forEach { minutes ->
                            Papierknopf(java.text.NumberFormat.getIntegerInstance(locale).format(minutes),
                                modifier = Modifier.weight(1f), aktiv = !speichert, ausgewaehlt = pauseAlarm.minutes == minutes) {
                                select(minutes)
                            }
                        }
                    }
                    Text(stringResource(R.string.zeit_pause_wecksignal))
                    val manager = context.getSystemService(android.app.AlarmManager::class.java)
                    if (android.os.Build.VERSION.SDK_INT >= 31 && !manager.canScheduleExactAlarms()) {
                        Text(stringResource(R.string.aufgabe_wecker_hinweis))
                        Papierknopf(stringResource(R.string.aufgabe_wecker_erlauben), aktiv = !speichert) {
                            context.startActivity(android.content.Intent(android.provider.Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                                android.net.Uri.parse("package:" + context.packageName)))
                        }
                    }
                }
            }
        }
        val pending = current?.let { stand.pauseRuns[it.id]?.pendingNotices }.orEmpty()
        if (current != null && pending.isNotEmpty()) item {
            Abschnitt(stringResource(R.string.zeit_feste_pausen)) {
                Text(stringResource(R.string.zeit_pause_ersetzt))
                Papierknopf(stringResource(R.string.ok), aktiv = !speichert) {
                    speichern({ state ->
                        val run = state.pauseRuns[current.id]
                        if (run == null) state else state.copy(pauseRuns = state.pauseRuns +
                            (current.id to run.copy(pendingNotices = run.pendingNotices - pending)))
                    }, {})
                }
            }
        }
        }
    }
}

@Composable
fun ZeiteintragEditor(entwurf: ZeitEntwurf, aktuell: () -> ZeitEntwurf, speichert: Boolean,
                     beiAenderung: (ZeitEntwurf) -> Unit, abbrechen: () -> Unit,
                     beiSichern: (ZeitEntwurf, Zeiteintrag) -> Unit, beiLoeschen: (ZeitEntwurf) -> Unit) {
    val context = LocalContext.current
    val locale = context.resources.configuration.locales[0]
    val original = entwurf.original
    val zone = remember(original.zone) { ZoneId.of(original.zone) }
    var now by remember { mutableStateOf(Zeiteintrag.currentMinute()) }
    var invalid by rememberSaveable(original.id) { mutableStateOf(false) }
    var loeschen by rememberSaveable(original.id) { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            now = Zeiteintrag.currentMinute()
            delay(60000 - System.currentTimeMillis() % 60000)
        }
    }
    BackHandler { if (!speichert) abbrechen() }
    fun setLocal(local: LocalDateTime, reference: Long, change: (Long) -> Unit) {
        val offsets = zone.rules.getValidOffsets(local)
        if (offsets.isEmpty()) { invalid = true; return }
        val previous = Instant.ofEpochSecond(reference * 60).atZone(zone).offset
        change(local.toEpochSecond(offsets.firstOrNull { it == previous } ?: offsets.first()) / 60)
        invalid = false
    }
    @Composable fun picker(label: String, minute: Long?, change: (Long) -> Unit) {
        val chosen = minute ?: now
        val local = Instant.ofEpochSecond(chosen * 60).atZone(zone)
        val dateText = DateFormat.getDateFormat(context).apply { timeZone = TimeZone.getTimeZone(zone) }.format(Date(chosen * 60000))
        val timeText = DateFormat.getTimeFormat(context).apply { timeZone = TimeZone.getTimeZone(zone) }.format(Date(chosen * 60000))
        Text(label)
        Row(Modifier.fillMaxWidth()) {
            Papierknopf(dateText, modifier = Modifier.weight(1f), aktiv = !speichert) {
                DatePickerDialog(context, { _, year, month, day ->
                    setLocal(local.toLocalDateTime().withYear(year).withDayOfMonth(1).withMonth(month + 1).withDayOfMonth(day), chosen, change)
                }, local.year, local.monthValue - 1, local.dayOfMonth).show()
            }
            Papierknopf(if (minute == null) stringResource(R.string.zeit_laufend) else timeText,
                modifier = Modifier.weight(1f), aktiv = !speichert) {
                TimePickerDialog(context, { _, hour, minutes ->
                    setLocal(local.toLocalDateTime().withHour(hour).withMinute(minutes), chosen, change)
                }, local.hour, local.minute, DateFormat.is24HourFormat(context)).show()
            }
        }
        val offsets = zone.rules.getValidOffsets(local.toLocalDateTime())
        if (minute != null && offsets.size > 1) Row {
            offsets.forEach { offset -> Papierknopf("UTC" + offset.id, aktiv = !speichert,
                ausgewaehlt = local.offset == offset) {
                change(local.toLocalDateTime().toEpochSecond(offset) / 60)
            } }
        }
    }
    Column(Modifier.fillMaxSize().background(Magnolie.papier).verticalScroll(rememberScrollState())) {
        Abschnitt(stringResource(R.string.zeit_korrektur)) {
            Schreibfeld(entwurf.kind, stringResource(R.string.zeit_art),
                { beiAenderung(aktuell().copy(kind = it)) }, aktiv = !speichert)
            picker(stringResource(R.string.zeit_beginn), entwurf.start) { beiAenderung(aktuell().copy(start = it, duration = null)) }
            picker(stringResource(R.string.zeit_ende), entwurf.end) { beiAenderung(aktuell().copy(end = it, duration = null)) }
            Text(original.zone)
            if (!entwurf.neu && original.endMinute == null && entwurf.end != null)
                Papierknopf(stringResource(R.string.zeit_laufend), aktiv = !speichert) { beiAenderung(aktuell().copy(end = null, duration = null)) }
            val effectivePause = runCatching { entwurf.pauseMinutes(now) }.getOrNull()
            Schreibfeld(if (!entwurf.pauseEdited && effectivePause != null) "%d".format(locale, effectivePause) else entwurf.pause,
                stringResource(R.string.zeit_pause), { beiAenderung(aktuell().copy(pause = it, pauseEdited = true)) }, aktiv = !speichert)
            val calculated = ((entwurf.end ?: now) - entwurf.start - (effectivePause ?: 0)).coerceAtLeast(0)
            Schreibfeld(entwurf.duration ?: Zeiteintrag.duration(calculated, locale), stringResource(R.string.zeit_gesamt),
                { text ->
                    val latest = aktuell()
                    val pauses = runCatching { latest.pauseMinutes(now) }.getOrNull()
                    beiAenderung(latest.copy(duration = text,
                        pause = if (!latest.pauseEdited && pauses != null) pauses.toString() else latest.pause,
                        pauseEdited = latest.pauseEdited || original.pauseMinute != null))
                }, aktiv = !speichert)
            Schreibfeld(entwurf.note, stringResource(R.string.baum_kontakt_notiz),
                { beiAenderung(aktuell().copy(note = it)) }, einzeilig = false, aktiv = !speichert)
            if (invalid) Text(stringResource(R.string.zeit_ungueltig), color = Magnolie.rot)
            Lederknopf(stringResource(R.string.sichern), aktiv = !speichert) {
                val latest = aktuell()
                val replacement = runCatching { latest.record() }.getOrNull()
                if (replacement == null) invalid = true
                else beiSichern(latest, replacement)
            }
            Papierknopf(stringResource(R.string.abbrechen), aktiv = !speichert, beiKlick = abbrechen)
            if (!entwurf.neu) Papierknopf(stringResource(R.string.loeschen), aktiv = !speichert) { loeschen = true }
        }
    }
    if (loeschen) AlertDialog(onDismissRequest = { if (!speichert) loeschen = false },
        title = { Text(stringResource(R.string.loeschen)) },
        text = { Text(stringResource(R.string.zeit_loeschen_frage)) },
        confirmButton = { TextButton(enabled = !speichert, onClick = { loeschen = false; beiLoeschen(aktuell()) }) {
            Text(stringResource(R.string.loeschen))
        } }, dismissButton = { TextButton(enabled = !speichert, onClick = { loeschen = false }) {
            Text(stringResource(R.string.abbrechen))
        } })
}
