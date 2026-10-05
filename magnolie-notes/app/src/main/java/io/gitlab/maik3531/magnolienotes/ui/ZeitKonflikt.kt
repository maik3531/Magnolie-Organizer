package io.gitlab.maik3531.magnolienotes.ui

import android.text.format.DateFormat
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungAbgleich
import java.text.NumberFormat
import java.time.ZoneId
import java.util.Date
import java.util.TimeZone

/** Immutable review snapshot: a background update must never change the choice being confirmed. */
internal data class ZeitKonfliktAuswahl(val local: Zeiteintrag, val versions: List<Zeiteintrag>)

@Composable
internal fun ZeitKonfliktDialog(auswahl: ZeitKonfliktAuswahl, now: Long, speichert: Boolean,
                                speichern: ZeitSpeichern, schliessen: () -> Unit) {
    val context = LocalContext.current
    val locale = context.resources.configuration.locales[0]
    AlertDialog(onDismissRequest = { if (!speichert) schliessen() },
        title = { Text(stringResource(R.string.baum_kontakt_konflikt)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                (listOf(auswahl.local) + auswahl.versions).forEachIndexed { index, entry ->
                    val version = stringResource(R.string.personal_sync_geaendert_titel) + " · " +
                        NumberFormat.getIntegerInstance(locale).format(index + 1)
                    Abschnitt(version) {
                        if (entry.deleted) Text(stringResource(R.string.loeschen)) else {
                            val zone = TimeZone.getTimeZone(ZoneId.of(entry.zone))
                            fun stamp(minute: Long): String {
                                val date = Date(minute * 60000)
                                return DateFormat.getDateFormat(context).apply { timeZone = zone }.format(date) + " · " +
                                    DateFormat.getTimeFormat(context).apply { timeZone = zone }.format(date)
                            }
                            val projected = entry.pausePlan?.project(entry, now) ?: entry
                            Wertzeile(stringResource(R.string.zeit_art), entry.type)
                            Wertzeile(stringResource(R.string.zeit_beginn), stamp(entry.startMinute))
                            Wertzeile(stringResource(R.string.zeit_ende), entry.endMinute?.let { stamp(it) }
                                ?: stringResource(R.string.zeit_laufend))
                            Text(entry.zone)
                            Wertzeile(stringResource(R.string.zeit_pause), NumberFormat.getIntegerInstance(locale)
                                .format(projected.pausedMinutes(now)))
                            Wertzeile(stringResource(R.string.zeit_gesamt), Zeiteintrag.duration(projected.totalMinutes(now), locale))
                            if (entry.note.isNotBlank()) Text(entry.note)
                        }
                        val choice = stringResource(if (entry.deleted) R.string.loeschen else R.string.personal_sync_wiederherstellen)
                        TextButton(enabled = !speichert, modifier = Modifier.semantics { contentDescription = "$choice · $version" },
                            onClick = {
                                speichern({ state -> ZeiterfassungAbgleich.resolve(state, auswahl.local.id, entry,
                                    auswahl.versions, auswahl.local) }, schliessen)
                            }) { Text(choice) }
                    }
                }
            }
        }, confirmButton = {},
        dismissButton = { TextButton(enabled = !speichert, onClick = schliessen) { Text(stringResource(R.string.abbrechen)) } })
}
