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
import io.gitlab.maik3531.magnolienotes.daten.PortableVorschau
import io.gitlab.maik3531.magnolienotes.journal.JournalIntervall
import io.gitlab.maik3531.magnolienotes.journal.JournalZustand
import io.gitlab.maik3531.magnolienotes.journal.SnapshotManifest
import io.gitlab.maik3531.magnolienotes.sicherung.AutoSicherungsIntervall
import io.gitlab.maik3531.magnolienotes.sicherung.AutoSicherungsStatus
import io.gitlab.maik3531.magnolienotes.sicherung.AutoSicherungsZustand
import java.time.Instant
import java.util.UUID

class JournalHandlungen(
    val beiIntervall: (JournalIntervall) -> Unit,
    val beiMaximum: (Int) -> Unit,
    val beiJetzt: () -> Unit,
    val beiWiederherstellen: (String, String, Boolean) -> Boolean,
    val beiLoeschen: (String) -> Unit,
    val beiPapierkorbSchalter: (Boolean, Int) -> Unit,
    val beiPapierkorbTage: (Boolean, Int) -> Unit,
    val beiPapierkorbWiederherstellen: (String) -> Unit,
    val beiPapierkorbLoeschen: (String) -> Unit,
    val beiPapierkorbLeeren: () -> Unit,
    val absturzberichtVorhanden: Boolean,
    val beiAbsturzberichtTeilen: () -> Unit,
    val portableImportBereit: Boolean,
    val portableVorschau: PortableVorschau?,
    val portableLaeuft: Boolean,
    val portableFehler: Boolean,
    val beiPortableExport: (String) -> Unit,
    val beiPortableDatei: () -> Unit,
    val beiPortablePruefen: (String) -> Unit,
    val beiPortableWiederherstellen: () -> Unit,
    val beiPortableAbbrechen: () -> Unit,
    val autoSicherung: AutoSicherungsZustand,
    val beiAutoOrdner: () -> Unit,
    val beiAutoPasswort: (String) -> Unit,
    val beiAutoAktiv: (Boolean) -> Unit,
    val beiAutoIntervall: (AutoSicherungsIntervall) -> Unit,
    val beiAutoAufbewahrung: (Int) -> Unit,
    val beiAutoJetzt: () -> Unit,
)

@Composable
fun JournalBlatt(zustand: JournalZustand, bestand: Bestand, handlungen: JournalHandlungen) {
    var vorschau by remember { mutableStateOf<SnapshotManifest?>(null) }
    var wiederherstellen by remember { mutableStateOf<SnapshotManifest?>(null) }
    var loeschen by remember { mutableStateOf<SnapshotManifest?>(null) }
    var papierkorbLoeschen by remember { mutableStateOf<String?>(null) }
    var papierkorbLeeren by remember { mutableStateOf(false) }
    var kontaktKonflikt by remember { mutableStateOf<Pair<SnapshotManifest, String>?>(null) }
    var maximumText by remember(zustand.maximum) { mutableStateOf(zustand.maximum.toString()) }
    var exportPasswort by remember { mutableStateOf<String?>(null) }
    var importPasswort by remember { mutableStateOf("") }
    var autoPasswort by remember { mutableStateOf<String?>(null) }
    var autoDanachAktivieren by remember { mutableStateOf(false) }
    var autoAufbewahrung by remember(handlungen.autoSicherung.aufbewahrung) {
        mutableStateOf(handlungen.autoSicherung.aufbewahrung.toString())
    }
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
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Schreibfeld(maximumText, stringResource(R.string.journal_maximum),
                    beiAenderung = { maximumText = it.filter(Char::isDigit).take(3) },
                    modifier = Modifier.weight(1f))
                Papierknopf(stringResource(R.string.ok), modifier = Modifier.padding(top = 7.dp)) {
                    val maximum = (maximumText.toIntOrNull() ?: zustand.maximum).coerceIn(1, 100)
                    maximumText = maximum.toString()
                    handlungen.beiMaximum(maximum)
                }
            }
            Text(stringResource(R.string.journal_maximum_hinweis), fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp, color = Magnolie.braunHell)
            Lederknopf(stringResource(R.string.journal_jetzt), modifier = Modifier.fillMaxWidth(),
                beiKlick = handlungen.beiJetzt)
            Papierknopf(stringResource(R.string.absturzbericht_teilen),
                modifier = Modifier.fillMaxWidth(), aktiv = handlungen.absturzberichtVorhanden,
                beiKlick = handlungen.beiAbsturzberichtTeilen)
        }
        Abschnitt(ueberschrift = stringResource(R.string.portable_titel),
            hinweis = stringResource(R.string.portable_hinweis)) {
            Lederknopf(stringResource(R.string.portable_export), modifier = Modifier.fillMaxWidth()) {
                exportPasswort = ""
            }
            Papierknopf(stringResource(R.string.portable_datei_oeffnen),
                modifier = Modifier.fillMaxWidth(), aktiv = !handlungen.portableLaeuft,
                beiKlick = handlungen.beiPortableDatei)
            if (handlungen.portableFehler) Text(stringResource(R.string.portable_fehler),
                color = Magnolie.rot, fontSize = 12.sp)
            Text(stringResource(R.string.auto_backup_titel), fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.Bold, fontSize = 14.sp, color = Magnolie.tinte,
                modifier = Modifier.padding(top = 12.dp))
            Text(stringResource(R.string.auto_backup_hinweis), fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp, color = Magnolie.braunHell)
            Schalterzeile(stringResource(R.string.auto_backup_aktiv), handlungen.autoSicherung.aktiviert) { an ->
                if (an && !handlungen.autoSicherung.passwortGesichert) {
                    autoDanachAktivieren = true; autoPasswort = ""
                } else handlungen.beiAutoAktiv(an)
            }
            Papierknopf(stringResource(if (handlungen.autoSicherung.ordnerGewaehlt)
                R.string.auto_backup_ordner_aendern else R.string.auto_backup_ordner_waehlen),
                modifier = Modifier.fillMaxWidth(), beiKlick = handlungen.beiAutoOrdner)
            Papierknopf(stringResource(if (handlungen.autoSicherung.passwortGesichert)
                R.string.auto_backup_passwort_aendern else R.string.auto_backup_passwort_setzen),
                modifier = Modifier.fillMaxWidth()) {
                autoDanachAktivieren = false; autoPasswort = ""
            }
            Text(stringResource(R.string.auto_backup_passwort_warnung), fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp, color = Magnolie.braunHell)
            Text(stringResource(R.string.auto_backup_intervall), fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.Bold, fontSize = 14.sp, color = Magnolie.tinte)
            Row(horizontalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.fillMaxWidth()) {
                listOf(AutoSicherungsIntervall.TAEGLICH to R.string.journal_taeglich,
                    AutoSicherungsIntervall.WOECHENTLICH to R.string.journal_woechentlich).forEach { (wert, text) ->
                    Papierknopf(stringResource(text), modifier = Modifier.weight(1f),
                        ausgewaehlt = handlungen.autoSicherung.intervall == wert) {
                        handlungen.beiAutoIntervall(wert)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Schreibfeld(autoAufbewahrung, stringResource(R.string.auto_backup_aufbewahrung),
                    beiAenderung = { autoAufbewahrung = it.filter(Char::isDigit).take(2) },
                    modifier = Modifier.weight(1f))
                Papierknopf(stringResource(R.string.ok), modifier = Modifier.padding(top = 7.dp)) {
                    val wert = (autoAufbewahrung.toIntOrNull() ?: handlungen.autoSicherung.aufbewahrung).coerceIn(2, 30)
                    autoAufbewahrung = wert.toString(); handlungen.beiAutoAufbewahrung(wert)
                }
            }
            Wertzeile(stringResource(R.string.auto_backup_letzter_erfolg),
                handlungen.autoSicherung.letzterErfolg?.let(Zeit::tagUndUhrzeit)
                    ?: stringResource(R.string.baum_nie))
            Wertzeile(stringResource(R.string.journal_status), autoStatusText(handlungen.autoSicherung.status))
            Lederknopf(stringResource(R.string.auto_backup_jetzt), modifier = Modifier.fillMaxWidth(),
                aktiv = handlungen.autoSicherung.aktiviert &&
                    handlungen.autoSicherung.status != AutoSicherungsStatus.LAEUFT,
                beiKlick = handlungen.beiAutoJetzt)
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
    exportPasswort?.let { passwort -> AlertDialog(onDismissRequest = { exportPasswort = null },
        title = { Text(stringResource(R.string.portable_export)) },
        text = { Schreibfeld(passwort, stringResource(R.string.portable_passwort),
            { exportPasswort = it.take(1024) }, passwort = true) },
        confirmButton = { TextButton(enabled = passwort.isNotEmpty(), onClick = {
            handlungen.beiPortableExport(passwort); exportPasswort = null
        }) { Text(stringResource(R.string.portable_export)) } },
        dismissButton = { TextButton(onClick = { exportPasswort = null }) {
            Text(stringResource(R.string.abbrechen)) } }) }
    autoPasswort?.let { passwort -> AlertDialog(onDismissRequest = {
        autoPasswort = null; autoDanachAktivieren = false
    }, title = { Text(stringResource(R.string.auto_backup_passwort_setzen)) },
        text = { Column {
            Text(stringResource(R.string.auto_backup_passwort_warnung))
            Schreibfeld(passwort, stringResource(R.string.portable_passwort),
                { autoPasswort = it.take(1024) }, passwort = true)
        } }, confirmButton = { TextButton(enabled = passwort.isNotEmpty(), onClick = {
            handlungen.beiAutoPasswort(passwort)
            if (autoDanachAktivieren) handlungen.beiAutoAktiv(true)
            autoPasswort = null; autoDanachAktivieren = false
        }) { Text(stringResource(R.string.ok)) } },
        dismissButton = { TextButton(onClick = {
            autoPasswort = null; autoDanachAktivieren = false
        }) { Text(stringResource(R.string.abbrechen)) } }) }
    if (handlungen.portableImportBereit && handlungen.portableVorschau == null) AlertDialog(
        onDismissRequest = handlungen.beiPortableAbbrechen,
        title = { Text(stringResource(R.string.portable_restore)) },
        text = { Column { Text(stringResource(R.string.portable_passwort_hinweis))
            Schreibfeld(importPasswort, stringResource(R.string.portable_passwort),
                { importPasswort = it.take(1024) }, passwort = true) } },
        confirmButton = { TextButton(enabled = importPasswort.isNotEmpty() && !handlungen.portableLaeuft,
            onClick = { handlungen.beiPortablePruefen(importPasswort) }) {
            Text(stringResource(R.string.portable_pruefen)) } },
        dismissButton = { TextButton(onClick = { importPasswort = ""; handlungen.beiPortableAbbrechen() }) {
            Text(stringResource(R.string.abbrechen)) } })
    handlungen.portableVorschau?.let { preview -> AlertDialog(
        onDismissRequest = handlungen.beiPortableAbbrechen,
        title = { Text(stringResource(R.string.portable_vorschau)) },
        text = { Text(stringResource(R.string.portable_vorschau_text, preview.notizen,
            preview.notizbuecher, preview.aufgaben, preview.papierkorb) + "\n\n" +
            stringResource(R.string.portable_restore_warnung)) },
        confirmButton = { TextButton(enabled = !handlungen.portableLaeuft, onClick = {
            importPasswort = ""; handlungen.beiPortableWiederherstellen()
        }) { Text(stringResource(R.string.portable_restore), color = Magnolie.rot) } },
        dismissButton = { TextButton(onClick = { importPasswort = ""; handlungen.beiPortableAbbrechen() }) {
            Text(stringResource(R.string.abbrechen)) } }) }
}

@Composable
private fun autoStatusText(status: AutoSicherungsStatus) = stringResource(when (status) {
    AutoSicherungsStatus.BEREIT -> R.string.auto_backup_status_bereit
    AutoSicherungsStatus.LAEUFT -> R.string.auto_backup_status_laeuft
    AutoSicherungsStatus.ERFOLG -> R.string.auto_backup_status_erfolg
    AutoSicherungsStatus.ERFOLG_AUFBEWAHRUNG_FEHLER -> R.string.auto_backup_status_aufbewahrung
    AutoSicherungsStatus.ORDNER_FEHLT -> R.string.auto_backup_status_ordner
    AutoSicherungsStatus.FREIGABE_FEHLT -> R.string.auto_backup_status_freigabe
    AutoSicherungsStatus.PASSWORT_FEHLT -> R.string.auto_backup_status_passwort
    AutoSicherungsStatus.SCHLUESSEL_FEHLT -> R.string.auto_backup_status_schluessel
    AutoSicherungsStatus.AUTHENTIFIZIERUNG_FEHLER -> R.string.auto_backup_status_auth
    AutoSicherungsStatus.PROVIDER_FEHLER -> R.string.auto_backup_status_provider
})

private fun groesse(bytes: Long) = if (bytes < 1024 * 1024) "${bytes / 1024} KiB" else "${bytes / 1024 / 1024} MiB"
