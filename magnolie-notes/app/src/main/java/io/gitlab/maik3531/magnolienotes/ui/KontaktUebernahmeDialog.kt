package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.baum.*

@Composable
fun KontaktUebernahmeDialog(vorschau: KontaktUebernahmeVorschau, laeuft: Boolean,
                            abbrechen: () -> Unit, bestaetigen: (List<KontaktAuswahl>) -> Unit) {
    var wahlen by remember(vorschau.id) { mutableStateOf(vorschau.eintraege.mapNotNull { eintrag ->
        eintrag.vorauswahl?.let { eintrag.gruppe.id to KontaktAuswahl(eintrag.gruppe.id, it,
            if (it == KontaktEntscheidung.NEU) null else eintrag.ziele.single().kontakt.rawContactId) }
    }.toMap()) }
    var ziele by remember(vorschau.id) { mutableStateOf(vorschau.eintraege.mapNotNull { eintrag ->
        eintrag.ziele.singleOrNull()?.let { eintrag.gruppe.id to it.kontakt.rawContactId }
    }.toMap()) }
    var rest by remember(vorschau.id) { mutableStateOf(false) }
    fun waehle(index: Int, entscheidung: KontaktEntscheidung) {
        val eintrag = vorschau.eintraege[index]
        val raw = if (entscheidung == KontaktEntscheidung.NEU) null else ziele[eintrag.gruppe.id]
        wahlen = wahlen + (eintrag.gruppe.id to KontaktAuswahl(eintrag.gruppe.id, entscheidung, raw))
        if (rest && eintrag.ziele.singleOrNull()?.stark == true) {
            vorschau.eintraege.drop(index + 1).filter { it.gruppe.id !in wahlen }.forEach { folge ->
                val ziel = folge.ziele.singleOrNull()
                if (ziel?.stark == true && (entscheidung !in setOf(KontaktEntscheidung.ERSETZEN, KontaktEntscheidung.NEUESTE) ||
                            ziel.kontakt.rawContactIds.size == 1) &&
                    (entscheidung != KontaktEntscheidung.NEUESTE || KontaktUebernahmePlan.neuesteMoeglich(folge, ziel))) {
                    ziele = ziele + (folge.gruppe.id to ziel.kontakt.rawContactId)
                    wahlen = wahlen + (folge.gruppe.id to KontaktAuswahl(folge.gruppe.id, entscheidung,
                        if (entscheidung == KontaktEntscheidung.NEU) null else ziel.kontakt.rawContactId))
                }
            }
        }
    }
    AlertDialog(onDismissRequest = { if (!laeuft) abbrechen() },
        title = { Text(stringResource(R.string.kontakt_review_titel)) },
        text = { Column(Modifier.heightIn(max = 520.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.baum_kontakt_noch_nicht_geschrieben))
            Row {
                Checkbox(checked = rest, onCheckedChange = { rest = it }, enabled = !laeuft)
                Text(stringResource(R.string.kontakt_review_rest))
            }
            vorschau.eintraege.forEachIndexed { index, eintrag ->
                val id = eintrag.gruppe.id
                val wahl = wahlen[id]
                val ziel = eintrag.ziele.singleOrNull { it.kontakt.rawContactId == ziele[id] }
                Text("${index + 1}. ${KontaktPruefung.name(eintrag.gruppe.kontakt)}", fontWeight = FontWeight.Bold)
                Text(stringResource(R.string.kontakt_review_fern), fontWeight = FontWeight.SemiBold)
                KontaktReviewInhalt(eintrag.gruppe.kontakt)
                if (eintrag.fernzeit > 0) Text(java.text.DateFormat.getDateTimeInstance().format(java.util.Date(eintrag.fernzeit)))
                eintrag.ziele.forEach { kandidat ->
                    Row {
                        RadioButton(selected = ziele[id] == kandidat.kontakt.rawContactId, enabled = !laeuft,
                            onClick = { ziele = ziele + (id to kandidat.kontakt.rawContactId); wahlen = wahlen - id })
                        Column {
                            Text(stringResource(R.string.kontakt_review_lokal), fontWeight = FontWeight.SemiBold)
                            KontaktReviewInhalt(kandidat.kontakt.daten)
                            Text(kandidat.kontakt.herkuenfte.joinToString(" · ") { it.accountName.ifBlank { it.accountType } })
                            if (kandidat.inhaltszeit > 0) Text(java.text.DateFormat.getDateTimeInstance().format(java.util.Date(kandidat.inhaltszeit)))
                        }
                    }
                }
                val optionen = listOf(
                    KontaktEntscheidung.BEHALTEN to R.string.kontakt_review_behalten,
                    KontaktEntscheidung.MISCHEN to R.string.baum_kontakt_karten_zusammenfuehren,
                    KontaktEntscheidung.ERSETZEN to R.string.journal_konflikt_ueberschreiben,
                    KontaktEntscheidung.NEU to R.string.kontakt_review_neu,
                    KontaktEntscheidung.NEUESTE to R.string.kontakt_review_neueste)
                optionen.forEach { (art, text) ->
                    val aktiv = art == KontaktEntscheidung.NEU || ziel != null && when (art) {
                        KontaktEntscheidung.NEUESTE -> KontaktUebernahmePlan.neuesteMoeglich(eintrag, ziel)
                        KontaktEntscheidung.ERSETZEN -> ziel.kontakt.rawContactIds.size == 1
                        else -> true
                    }
                    Row {
                        RadioButton(selected = wahl?.entscheidung == art, enabled = aktiv && !laeuft,
                            onClick = { waehle(index, art) })
                        Text(stringResource(text))
                    }
                }
                if (ziel != null && wahl?.entscheidung == KontaktEntscheidung.MISCHEN) {
                    val a = ziel.kontakt.daten; val b = eintrag.gruppe.kontakt
                    val felder = listOf(
                        Triple(setOf("vorname", "nachname", "anzeigename"), R.string.art_kontakt,
                            listOf(a.vorname, a.nachname, a.anzeigename, a.vcardName) != listOf(b.vorname, b.nachname, b.anzeigename, b.vcardName)),
                        Triple(setOf("firma"), R.string.baum_kontakt_firma, a.firma != b.firma),
                        Triple(setOf("geburtstag"), R.string.baum_kontakt_geburtstag, a.geburtstag != b.geburtstag),
                        Triple(setOf("jubilaeum"), R.string.baum_kontakt_jubilaeum, a.jubilaeum != b.jubilaeum),
                        Triple(setOf("notiz"), R.string.baum_kontakt_notiz, a.notiz != b.notiz),
                        Triple(setOf("foto"), R.string.baum_kontakt_bild, a.foto != b.foto && ziel.kontakt.rawContactIds.size == 1))
                    felder.filter { it.third }.forEach { (keys, label, _) -> Row {
                        Checkbox(checked = wahl.fernfelder.containsAll(keys), enabled = !laeuft, onCheckedChange = { an ->
                            wahlen = wahlen + (id to wahl.copy(fernfelder = if (an) wahl.fernfelder + keys else wahl.fernfelder - keys,
                                geburtsnameBehalten = wahl.geburtsnameBehalten && (an || "nachname" !in keys)))
                        })
                        Text(stringResource(R.string.kontakt_review_fern) + ": " + stringResource(label))
                    } }
                }
                if (ziel != null && wahl != null && ziel.kontakt.daten.nachname.isNotBlank() &&
                    eintrag.gruppe.kontakt.nachname.isNotBlank() && ziel.kontakt.daten.nachname != eintrag.gruppe.kontakt.nachname &&
                    (wahl.entscheidung == KontaktEntscheidung.ERSETZEN ||
                        wahl.entscheidung == KontaktEntscheidung.NEUESTE && eintrag.fernzeit > ziel.inhaltszeit ||
                        wahl.entscheidung == KontaktEntscheidung.MISCHEN && "nachname" in wahl.fernfelder)) {
                    Row {
                        Checkbox(checked = wahl.geburtsnameBehalten, enabled = !laeuft, onCheckedChange = { an ->
                            wahlen = wahlen + (id to wahl.copy(geburtsnameBehalten = an))
                        })
                        Text(stringResource(R.string.kontakt_review_geburtsname, ziel.kontakt.daten.nachname))
                    }
                }
            }
        } },
        confirmButton = { TextButton(enabled = !laeuft && wahlen.size == vorschau.eintraege.size,
            onClick = { bestaetigen(vorschau.eintraege.map { wahlen.getValue(it.gruppe.id) }) }) { Text(stringResource(R.string.ok)) } },
        dismissButton = { TextButton(enabled = !laeuft, onClick = abbrechen) { Text(stringResource(R.string.abbrechen)) } })
}

@Composable
private fun KontaktReviewInhalt(k: KontaktDaten) {
    Text(KontaktPruefung.name(k))
    if (k.anzeigename.isNotBlank() && k.anzeigename != KontaktPruefung.name(k)) Text(k.anzeigename)
    if (k.firma.isNotBlank()) Text(stringResource(R.string.baum_kontakt_firma) + ": " + k.firma)
    k.telefone.forEach { Text(stringResource(R.string.baum_kontakt_telefon) + ": " + it.wert) }
    k.emailEintraege.forEach { Text(stringResource(R.string.baum_kontakt_email) + ": " + it.wert) }
    k.anschriften.forEach { Text(listOf(it.strasse, it.plz, it.ort, it.region, it.land).filter(String::isNotBlank).joinToString(", ")) }
    if (k.geburtstag.isNotBlank()) Text(stringResource(R.string.baum_kontakt_geburtstag) + ": " + k.geburtstag)
    if (k.jubilaeum.isNotBlank()) Text(stringResource(R.string.baum_kontakt_jubilaeum) + ": " + k.jubilaeum)
    if (k.notiz.isNotBlank()) Text(k.notiz)
    if (k.foto.isNotBlank()) Text(stringResource(R.string.baum_kontakt_bild) + ": " + stringResource(R.string.baum_kontakt_vorhanden))
}
