package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Bestand
import io.gitlab.maik3531.magnolienotes.journal.JournalIntervall
import io.gitlab.maik3531.magnolienotes.journal.JournalZustand
import io.gitlab.maik3531.magnolienotes.journal.SnapshotManifest
import java.time.Instant
import java.util.UUID

class JournalHandlungen(
    val beiIntervall: (JournalIntervall) -> Unit,
    val beiJetzt: () -> Unit,
    val beiWiederherstellen: (String, String, Boolean) -> Boolean,
    val beiLoeschen: (String) -> Unit,
    val beiPapierkorbSchalter: (Boolean, Int) -> Unit,
    val beiPapierkorbTage: (Boolean, Int) -> Unit,
    val beiPapierkorbWiederherstellen: (String) -> Unit,
    val beiPapierkorbLoeschen: (String) -> Unit,
    val beiPapierkorbLeeren: () -> Unit
)

@Composable
fun JournalBlatt(zustand: JournalZustand, bestand: Bestand, handlungen: JournalHandlungen) {
    var vorschau by remember { mutableStateOf<SnapshotManifest?>(null) }
    var wiederherstellen by remember { mutableStateOf<SnapshotManifest?>(null) }
    var loeschen by remember { mutableStateOf<SnapshotManifest?>(null) }
    var papierkorbLoeschen by remember { mutableStateOf<String?>(null) }
    var papierkorbLeeren by remember { mutableStateOf(false) }
    var kontaktKonflikt by remember { mutableStateOf<Pair<SnapshotManifest, String>?>(null) }
    val intervalle = listOf(JournalIntervall.AUS, JournalIntervall.SECHS_STUNDEN,
        JournalIntervall.ZWOELF_STUNDEN, JournalIntervall.TAEGLICH, JournalIntervall.WOECHENTLICH)
    val intervalNamen = listOf(R.string.journal_aus, R.string.journal_6h, R.string.journal_12h,
        R.string.journal_taeglich, R.string.journal_woechentlich)
    Column(Modifier.fillMaxSize().background(Magnolie.papier).verticalScroll(rememberScrollState())) {
        Abschnitt(ueberschrift = stringResource(R.string.papierkorb_titel),
            hinweis = stringResource(R.string.papierkorb_hinweis)) {
            Schalterzeile(stringResource(R.string.papierkorb_titel), bestand.papierkorbEinstellungen.an) {
                handlungen.beiPapierkorbSchalter(it, bestand.papierkorbEinstellungen.tage)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf(0, 7, 30, 90, 365).forEach { tage ->
                    Papierknopf(tage.toString(), ausgewaehlt = bestand.papierkorbEinstellungen.tage == tage) {
                        handlungen.beiPapierkorbTage(bestand.papierkorbEinstellungen.an, tage)
                    }
                }
            }
            bestand.papierkorb.forEach { eintrag ->
                Text("${lokalisierterText(TechnischeWerteLokalisierung.art(eintrag.art))}: ${eintrag.name}",
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Papierknopf(stringResource(R.string.baum_annehmen)) {
                        handlungen.beiPapierkorbWiederherstellen(eintrag.id)
                    }
                    Papierknopf(stringResource(R.string.loeschen)) { papierkorbLoeschen = eintrag.id }
                }
            }
            if (bestand.papierkorb.isNotEmpty()) {
                Papierknopf(stringResource(R.string.papierkorb_leeren)) { papierkorbLeeren = true }
            }
        }
        Abschnitt(ueberschrift = stringResource(R.string.journal_titel),
            hinweis = stringResource(R.string.journal_hinweis)) {
            Wertzeile(stringResource(R.string.journal_zuletzt), zustand.last?.let(Zeit::tagUndUhrzeit)
                ?: stringResource(R.string.baum_nie))
            val next = zustand.interval.millis?.let { i -> zustand.last?.plus(i) }
            Wertzeile(stringResource(R.string.journal_naechste), next?.let(Zeit::tagUndUhrzeit)
                ?: stringResource(R.string.journal_aus))
            Wertzeile(stringResource(R.string.journal_status), zustand.status.ifBlank {
                stringResource(R.string.journal_bereit) })
            Text(stringResource(R.string.journal_intervall), fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.Bold, fontSize = 14.sp, color = Magnolie.tinte,
                modifier = Modifier.padding(top = 10.dp))
            intervalle.zip(intervalNamen).chunked(2).forEach { row ->
                Row(horizontalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.fillMaxWidth()) {
                    row.forEach { (interval, text) -> Papierknopf(stringResource(text),
                        ausgewaehlt = zustand.interval == interval, modifier = Modifier.weight(1f)) {
                        handlungen.beiIntervall(interval)
                    } }
                }
            }
            Lederknopf(stringResource(R.string.journal_jetzt), modifier = Modifier.fillMaxWidth(),
                beiKlick = handlungen.beiJetzt)
        }
        Abschnitt(stringResource(R.string.journal_liste)) {
            if (zustand.entries.isEmpty()) Text(stringResource(R.string.journal_leer), color = Magnolie.braunHell)
            zustand.entries.forEach { entry ->
                Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                    val grund = lokalisierterText(TechnischeWerteLokalisierung.journalGrund(entry.reason))
                    val domaene = lokalisierterText(TechnischeWerteLokalisierung.journalDomaene(entry.domain))
                    val zusammenfassung = lokalisierterText(
                        TechnischeWerteLokalisierung.journalZusammenfassung(entry.summary))
                    Text(Zeit.tagUndUhrzeit(Instant.parse(entry.createdUtc).toEpochMilli()),
                        fontFamily = FontFamily.Serif, fontWeight = FontWeight.Bold, color = Magnolie.tinte)
                    Text("$grund · $domaene · ${groesse(entry.payload.size)} · ${stringResource(R.string.journal_integritaet)}",
                        fontFamily = FontFamily.SansSerif, fontSize = 11.sp, color = Magnolie.braunHell)
                    Text(zusammenfassung, fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.tinte)
                    BoxWithConstraints(Modifier.fillMaxWidth()) {
                        if (maxWidth < 380.dp) Column {
                            Lederknopf(stringResource(R.string.journal_restore), modifier = Modifier.fillMaxWidth()) {
                                wiederherstellen = entry
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.fillMaxWidth()) {
                                Papierknopf(stringResource(R.string.journal_vorschau), modifier = Modifier.weight(1f)) {
                                    vorschau = entry
                                }
                                Papierknopf(stringResource(R.string.loeschen), modifier = Modifier.weight(1f)) {
                                    loeschen = entry
                                }
                            }
                        } else Row(horizontalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.fillMaxWidth()) {
                            Papierknopf(stringResource(R.string.journal_vorschau), modifier = Modifier.weight(1f)) {
                                vorschau = entry
                            }
                            Lederknopf(stringResource(R.string.journal_restore), modifier = Modifier.weight(1.55f)) {
                                wiederherstellen = entry
                            }
                            Papierknopf(stringResource(R.string.loeschen), modifier = Modifier.weight(1f)) {
                                loeschen = entry
                            }
                        }
                    }
                }
            }
        }
    }
    vorschau?.let { entry -> AlertDialog(onDismissRequest = { vorschau = null },
        title = { Text(stringResource(R.string.journal_vorschau)) },
        text = { Text("${lokalisierterText(TechnischeWerteLokalisierung.journalZusammenfassung(entry.summary))}\n" +
            "${lokalisierterText(TechnischeWerteLokalisierung.journalGrund(entry.reason))}\n" +
            "${entry.payload.hash}\n${entry.syncEpoch}") },
        confirmButton = { TextButton(onClick = { vorschau = null }) { Text(stringResource(R.string.ok)) } }) }
    wiederherstellen?.let { entry -> AlertDialog(onDismissRequest = { wiederherstellen = null },
        title = { Text(stringResource(R.string.journal_restore)) },
        text = { Text(stringResource(R.string.journal_restore_frage,
            lokalisierterText(TechnischeWerteLokalisierung.journalZusammenfassung(entry.summary)))) },
        confirmButton = { TextButton(onClick = {
            val operation = UUID.randomUUID().toString()
            if (!handlungen.beiWiederherstellen(entry.uuid, operation, false) && entry.domain == "android-system-contacts") {
                kontaktKonflikt = entry to operation
            }
            wiederherstellen = null
        }) { Text(stringResource(R.string.journal_restore)) } },
        dismissButton = { TextButton(onClick = { wiederherstellen = null }) { Text(stringResource(R.string.abbrechen)) } }) }
    loeschen?.let { entry -> AlertDialog(onDismissRequest = { loeschen = null },
        title = { Text(stringResource(R.string.loeschen)) }, text = { Text(stringResource(R.string.journal_loeschen_frage)) },
        confirmButton = { TextButton(onClick = { handlungen.beiLoeschen(entry.uuid); loeschen = null }) {
            Text(stringResource(R.string.loeschen)) } }, dismissButton = { TextButton(onClick = { loeschen = null }) {
            Text(stringResource(R.string.abbrechen)) } }) }
    kontaktKonflikt?.let { (entry, operation) -> AlertDialog(onDismissRequest = { kontaktKonflikt = null },
        title = { Text(stringResource(R.string.journal_kontakt_konflikt)) },
        text = { Text(stringResource(R.string.journal_kontakt_konflikt_frage,
            lokalisierterText(TechnischeWerteLokalisierung.journalZusammenfassung(entry.summary)))) },
        confirmButton = { TextButton(onClick = {
            handlungen.beiWiederherstellen(entry.uuid, operation, true); kontaktKonflikt = null
        }) { Text(stringResource(R.string.journal_konflikt_ueberschreiben)) } },
        dismissButton = { TextButton(onClick = { kontaktKonflikt = null }) { Text(stringResource(R.string.abbrechen)) } }) }
    papierkorbLoeschen?.let { id -> AlertDialog(onDismissRequest = { papierkorbLoeschen = null },
        title = { Text(stringResource(R.string.papierkorb_endgueltig_titel)) },
        text = { Text(stringResource(R.string.papierkorb_endgueltig_hinweis)) },
        confirmButton = { TextButton(onClick = {
            handlungen.beiPapierkorbLoeschen(id); papierkorbLoeschen = null
        }) { Text(stringResource(R.string.loeschen), color = Magnolie.rot) } },
        dismissButton = { TextButton(onClick = { papierkorbLoeschen = null }) {
            Text(stringResource(R.string.abbrechen)) } }) }
    if (papierkorbLeeren) AlertDialog(onDismissRequest = { papierkorbLeeren = false },
        title = { Text(stringResource(R.string.papierkorb_leeren)) },
        text = { Text(pluralStringResource(R.plurals.papierkorb_leeren_hinweis,
            bestand.papierkorb.size, bestand.papierkorb.size)) },
        confirmButton = { TextButton(onClick = {
            handlungen.beiPapierkorbLeeren(); papierkorbLeeren = false
        }) { Text(stringResource(R.string.papierkorb_leeren), color = Magnolie.rot) } },
        dismissButton = { TextButton(onClick = { papierkorbLeeren = false }) {
            Text(stringResource(R.string.abbrechen)) } })
}

private fun groesse(bytes: Long) = if (bytes < 1024 * 1024) "${bytes / 1024} KiB" else "${bytes / 1024 / 1024} MiB"
