package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

/** Die Fächer, in die eine Aufgabe nach ihrer Fälligkeit fällt. */
private enum class Fach { UEBERFAELLIG, HEUTE, MORGEN, WOCHE, SPAETER, OHNE, ERLEDIGT }

private fun fachVon(aufgabe: Aufgabe): Fach {
    if (aufgabe.erledigt) return Fach.ERLEDIGT
    if (aufgabe.faellig.isBlank()) return Fach.OHNE
    val tage = tageBis(aufgabe.faellig) ?: return Fach.OHNE
    return when {
        tage < 0 -> Fach.UEBERFAELLIG
        tage == 0 -> Fach.HEUTE
        tage == 1 -> Fach.MORGEN
        tage <= 7 -> Fach.WOCHE
        else -> Fach.SPAETER
    }
}

private fun tageBis(isoDatum: String): Int? {
    val tag = runCatching {
        SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).parse(isoDatum)
    }.getOrNull() ?: return null
    val ziel = Calendar.getInstance().apply {
        time = tag
        set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0)
        set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
    }
    val heute = Calendar.getInstance().apply {
        set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0)
        set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
    }
    return ((ziel.timeInMillis - heute.timeInMillis) / 86_400_000L).toInt()
}

/**
 * Das Aufgabenblatt: was ansteht, nach Fälligkeit geordnet. Überfälliges
 * steht oben und in Signalrot, Erledigtes ganz unten und durchgestrichen.
 */
@Composable
fun AufgabenBlatt(
    aufgaben: List<Aufgabe>,
    beiOeffnen: (Aufgabe) -> Unit,
    beiAbhaken: (Aufgabe, Boolean) -> Unit,
    beiNeu: () -> Unit,
    modifier: Modifier = Modifier
) {
    val koepfe = mapOf(
        Fach.UEBERFAELLIG to stringResource(R.string.aufgabe_ueberfaellig_kopf),
        Fach.HEUTE to stringResource(R.string.aufgabe_heute_kopf),
        Fach.MORGEN to stringResource(R.string.aufgabe_morgen_kopf),
        Fach.WOCHE to stringResource(R.string.aufgabe_woche_kopf),
        Fach.SPAETER to stringResource(R.string.aufgabe_spaeter_kopf),
        Fach.OHNE to stringResource(R.string.aufgabe_ohne_kopf),
        Fach.ERLEDIGT to stringResource(R.string.aufgabe_erledigt_kopf)
    )
    val nachFach = Fach.entries.map { fach ->
        fach to aufgaben.filter { fachVon(it) == fach }
            .sortedWith(compareBy({ it.faellig.ifBlank { "9999" } }, { it.prio }))
    }.filter { it.second.isNotEmpty() }

    val zusammenhang = LocalContext.current
    // Ab Android 12 muss der Mensch genaue Wecker ausdrücklich erlauben.
    // Ohne sie weckt die App zwar trotzdem, aber gegebenenfalls verspätet.
    val weckerKnapp = remember(aufgaben) {
        val wecker = zusammenhang.getSystemService(android.app.AlarmManager::class.java)
        android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S &&
            wecker?.canScheduleExactAlarms() == false &&
            aufgaben.any { it.erinnern && !it.erledigt && it.faellig.isNotBlank() }
    }

    Column(modifier.fillMaxSize().background(Magnolie.papier)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.End
        ) {
            Lederknopf(stringResource(R.string.aufgabe_neu), beiKlick = beiNeu)
        }

        if (weckerKnapp) {
            Column(
                Modifier.fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 4.dp)
                    .background(Magnolie.papierTief, RoundedCornerShape(4.dp))
                    .border(1.dp, Magnolie.rot.copy(alpha = 0.5f), RoundedCornerShape(4.dp))
                    .padding(12.dp)
            ) {
                Text(
                    stringResource(R.string.aufgabe_wecker_hinweis),
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp,
                    lineHeight = 18.sp,
                    color = Magnolie.tinte
                )
                Box(Modifier.padding(top = 8.dp)) {
                    Papierknopf(stringResource(R.string.aufgabe_wecker_erlauben)) {
                        runCatching {
                            zusammenhang.startActivity(
                                android.content.Intent(
                                    android.provider.Settings
                                        .ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                                    android.net.Uri.parse("package:" + zusammenhang.packageName)
                                ).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                            )
                        }
                    }
                }
            }
        }

        if (aufgaben.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    stringResource(R.string.aufgabe_leer),
                    fontFamily = FontFamily.Serif,
                    fontSize = 15.sp,
                    color = Magnolie.braunHell,
                    modifier = Modifier.padding(36.dp)
                )
            }
            return@Column
        }

        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 28.dp)) {
            nachFach.forEach { (fach, stueck) ->
                item(key = "kopf-" + fach.name) {
                    Row(
                        Modifier.fillMaxWidth()
                            .padding(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            koepfe[fach].orEmpty(),
                            fontFamily = FontFamily.SansSerif,
                            fontWeight = FontWeight.Bold,
                            fontSize = 12.sp,
                            color = if (fach == Fach.UEBERFAELLIG) Magnolie.rot else Magnolie.braun
                        )
                        Box(
                            Modifier.padding(start = 10.dp)
                                .weight(1f).height(1.dp).background(Magnolie.linie)
                        )
                    }
                }
                items(stueck, key = { it.id }) { aufgabe ->
                    Aufgabenzeile(aufgabe, fach, beiOeffnen, beiAbhaken)
                }
            }
        }
    }
}

@Composable
private fun Aufgabenzeile(
    aufgabe: Aufgabe,
    fach: Fach,
    beiOeffnen: (Aufgabe) -> Unit,
    beiAbhaken: (Aufgabe, Boolean) -> Unit
) {
    val zeilenZusammenhang = LocalContext.current
    Row(
        Modifier.fillMaxWidth()
            .clickable { beiOeffnen(aufgabe) }
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.Top
    ) {
        Haekchen(aufgabe.erledigt) { beiAbhaken(aufgabe, !aufgabe.erledigt) }
        Column(Modifier.padding(start = 12.dp).weight(1f)) {
            Text(
                aufgabe.anzeigeTitel,
                fontFamily = FontFamily.Serif,
                fontWeight = if (aufgabe.prio == 1) FontWeight.Bold else FontWeight.SemiBold,
                fontSize = 16.sp,
                color = if (aufgabe.erledigt) Magnolie.braunHell else Magnolie.tinte,
                textDecoration = if (aufgabe.erledigt) TextDecoration.LineThrough else null,
                maxLines = 2
            )
            if (aufgabe.notiz.isNotBlank()) {
                Text(
                    aufgabe.notiz.replace(Regex("\\s+"), " ").trim(),
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp,
                    lineHeight = 17.sp,
                    color = Magnolie.braunHell,
                    maxLines = 2,
                    modifier = Modifier.padding(top = 2.dp)
                )
            }
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val wann = Erinnerung.faelligkeitInWorten(zeilenZusammenhang, aufgabe.faellig)
                if (wann.isNotBlank()) {
                    Text(
                        wann,
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 11.sp,
                        fontWeight = if (fach == Fach.UEBERFAELLIG) FontWeight.Bold else FontWeight.Normal,
                        color = if (fach == Fach.UEBERFAELLIG) Magnolie.rot else Magnolie.goldDunkel
                    )
                }
                if (aufgabe.prio == 1) {
                    Text(
                        stringResource(R.string.aufgabe_prio1),
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 11.sp,
                        color = Magnolie.rot
                    )
                }
                if (aufgabe.erinnern) {
                    val weckerBeschreibung = stringResource(R.string.aufgabe_erinnerung_aktiv)
                    Text(
                        "⏰",
                        fontSize = 11.sp,
                        color = Magnolie.braunHell,
                        modifier = Modifier.semantics {
                            contentDescription = weckerBeschreibung
                        }
                    )
                }
                if (aufgabe.vonZweig.isNotBlank()) {
                    Text(
                        stringResource(R.string.aufgabe_von, aufgabe.vonZweig),
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 11.sp,
                        color = Magnolie.filz
                    )
                }
            }
        }
    }
    Box(
        Modifier.fillMaxWidth().padding(start = 60.dp, end = 14.dp)
            .height(1.dp).background(Magnolie.linie)
    )
}

/** Ein Häkchenkästchen im Federstrich des Organizers. */
@Composable
private fun Haekchen(gesetzt: Boolean, beiKlick: () -> Unit) {
    val beschreibung = stringResource(
        if (gesetzt) R.string.aufgabe_als_offen_markieren
        else R.string.aufgabe_als_erledigt_markieren
    )
    Box(
        Modifier
            .size(28.dp)
            .border(1.5.dp, if (gesetzt) Magnolie.goldDunkel else Magnolie.linieStark, RoundedCornerShape(3.dp))
            .background(if (gesetzt) Magnolie.gold.copy(alpha = 0.25f) else Magnolie.papier)
            .semantics { contentDescription = beschreibung }
            .clickable(onClick = beiKlick),
        contentAlignment = Alignment.Center
    ) {
        if (gesetzt) {
            Text("✓", fontSize = 17.sp, color = Magnolie.braun, fontWeight = FontWeight.Bold)
        }
    }
}

/**
 * Das Schreibblatt einer Aufgabe. Fremde Aufgaben – die vom Rechner kamen –
 * lassen sich nur abhaken; alles andere gehört dem Ursprung.
 */
@Composable
fun AufgabenEditor(
    aufgabe: Aufgabe,
    partnernamen: List<Pair<String, String>>,
    beiSichern: (Aufgabe) -> Unit,
    beiLoeschen: () -> Unit,
    beiWeitergeben: (List<String>) -> Unit,
    beiZurueck: () -> Unit,
    modifier: Modifier = Modifier
) {
    var titel by remember(aufgabe.id) { mutableStateOf(aufgabe.titel) }
    var notiz by remember(aufgabe.id) { mutableStateOf(aufgabe.notiz) }
    var faellig by remember(aufgabe.id) { mutableStateOf(aufgabe.faellig) }
    var prio by remember(aufgabe.id) { mutableStateOf(aufgabe.prio) }
    var erinnern by remember(aufgabe.id) { mutableStateOf(aufgabe.erinnern) }
    var vorlauf by remember(aufgabe.id) { mutableStateOf(aufgabe.vorlaufTage) }
    var stunde by remember(aufgabe.id) { mutableStateOf(aufgabe.erinnerungsMinute / 60) }
    var fragtLoeschen by remember { mutableStateOf(false) }
    var fragtGeben by remember { mutableStateOf(false) }

    fun aktuell() = aufgabe.copy(
        titel = titel, notiz = notiz, faellig = faellig, prio = prio,
        erinnern = erinnern, vorlaufTage = vorlauf, erinnerungsMinute = stunde * 60
    )

    Column(modifier.fillMaxSize().background(Magnolie.papier)) {
        Einband(titel.ifBlank { stringResource(R.string.aufgabe_neu) }) {
            Rundknopf("‹", beschreibung = stringResource(R.string.zurueck)) {
                beiSichern(aktuell()); beiZurueck()
            }
        }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).navigationBarsPadding()
                .imePadding()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            if (aufgabe.vonZweig.isNotBlank()) {
                Text(
                    stringResource(R.string.aufgabe_von, aufgabe.vonZweig),
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp,
                    color = Magnolie.filz
                )
            }
            Schreibfeld(
                wert = titel,
                beschriftung = stringResource(R.string.aufgabe_titel),
                beiAenderung = { titel = it },
                serifen = true
            )
            Schreibfeld(
                wert = notiz,
                beschriftung = stringResource(R.string.aufgabe_notiz),
                beiAenderung = { notiz = it },
                einzeilig = false,
                serifen = true
            )
            Datumfeld(faellig) { faellig = it }

            Text(
                stringResource(R.string.aufgabe_prio),
                fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.braunHell
            )
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(
                    1 to stringResource(R.string.aufgabe_prio1),
                    2 to stringResource(R.string.aufgabe_prio2),
                    3 to stringResource(R.string.aufgabe_prio3)
                ).forEach { (wert, name) ->
                    Box(
                        Modifier
                            .background(
                                if (prio == wert) Magnolie.gold.copy(alpha = 0.35f)
                                else Magnolie.papierTief,
                                RoundedCornerShape(3.dp)
                            )
                            .border(
                                1.dp,
                                if (prio == wert) Magnolie.goldDunkel else Magnolie.linie,
                                RoundedCornerShape(3.dp)
                            )
                            .clickable { prio = wert }
                            .padding(horizontal = 12.dp, vertical = 8.dp)
                    ) {
                        Text(
                            name,
                            fontFamily = FontFamily.SansSerif,
                            fontSize = 13.sp,
                            color = if (wert == 1) Magnolie.rot else Magnolie.tinte
                        )
                    }
                }
            }

            val erinnerungBeschreibung = stringResource(R.string.aufgabe_erinnern)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    stringResource(R.string.aufgabe_erinnern),
                    fontFamily = FontFamily.SansSerif, fontSize = 13.sp,
                    color = Magnolie.tinte, modifier = Modifier.weight(1f)
                )
                Switch(
                    checked = erinnern,
                    onCheckedChange = { erinnern = it },
                    modifier = Modifier.semantics {
                        contentDescription = erinnerungBeschreibung
                    },
                    colors = SwitchDefaults.colors(
                        checkedThumbColor = Magnolie.gold,
                        checkedTrackColor = Magnolie.leder,
                        uncheckedThumbColor = Magnolie.braunHell,
                        uncheckedTrackColor = Magnolie.papierTief,
                        uncheckedBorderColor = Magnolie.linieStark
                    )
                )
            }
            if (erinnern) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        stringResource(R.string.aufgabe_vorlauf),
                        fontFamily = FontFamily.SansSerif, fontSize = 12.sp,
                        color = Magnolie.braunHell
                    )
                    Rundknopf(
                        "−", beschreibung = stringResource(R.string.aufgabe_vorlauf_verringern)
                    ) { if (vorlauf > 0) vorlauf-- }
                    Text(
                        vorlauf.toString(),
                        fontFamily = FontFamily.Monospace, fontSize = 15.sp, color = Magnolie.tinte
                    )
                    Rundknopf(
                        "+", beschreibung = stringResource(R.string.aufgabe_vorlauf_erhoehen)
                    ) { if (vorlauf < 14) vorlauf++ }
                    Text(
                        stringResource(R.string.aufgabe_uhrzeit),
                        fontFamily = FontFamily.SansSerif, fontSize = 12.sp,
                        color = Magnolie.braunHell,
                        modifier = Modifier.padding(start = 8.dp)
                    )
                    Rundknopf(
                        "−", beschreibung = stringResource(R.string.aufgabe_stunde_verringern)
                    ) { if (stunde > 0) stunde-- }
                    Text(
                        erinnerungsUhrzeit(stunde),
                        fontFamily = FontFamily.Monospace, fontSize = 15.sp, color = Magnolie.tinte
                    )
                    Rundknopf(
                        "+", beschreibung = stringResource(R.string.aufgabe_stunde_erhoehen)
                    ) { if (stunde < 23) stunde++ }
                }
                if (faellig.isBlank()) {
                    Text(
                        stringResource(R.string.aufgabe_kein_datum),
                        fontFamily = FontFamily.SansSerif, fontSize = 11.sp, color = Magnolie.rot
                    )
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Lederknopf(stringResource(R.string.sichern)) { beiSichern(aktuell()); beiZurueck() }
                Papierknopf(
                    stringResource(R.string.aufgabe_weitergeben),
                    aktiv = partnernamen.isNotEmpty() && !aufgabe.istFremd
                ) { beiSichern(aktuell()); fragtGeben = true }
                Papierknopf(stringResource(R.string.loeschen)) { fragtLoeschen = true }
            }
        }
    }

    if (fragtLoeschen) {
        AlertDialog(
            onDismissRequest = { fragtLoeschen = false },
            containerColor = Magnolie.papier,
            title = { Text(stringResource(R.string.aufgabe_loeschen), fontFamily = FontFamily.Serif) },
            text = { Text(stringResource(R.string.wirklich_loeschen)) },
            confirmButton = {
                TextButton(onClick = { fragtLoeschen = false; beiLoeschen(); beiZurueck() }) {
                    Text(stringResource(R.string.loeschen), color = Magnolie.rot)
                }
            },
            dismissButton = {
                TextButton(onClick = { fragtLoeschen = false }) {
                    Text(stringResource(R.string.abbrechen), color = Magnolie.braun)
                }
            }
        )
    }

    if (fragtGeben) {
        AlertDialog(
            onDismissRequest = { fragtGeben = false },
            containerColor = Magnolie.papier,
            title = {
                Text(stringResource(R.string.aufgabe_weitergeben), fontFamily = FontFamily.Serif)
            },
            text = {
                Column {
                    partnernamen.forEach { (kennung, name) ->
                        Text(
                            name,
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { fragtGeben = false; beiWeitergeben(listOf(kennung)) }
                                .padding(vertical = 10.dp),
                            fontFamily = FontFamily.SansSerif,
                            fontSize = 14.sp,
                            color = Magnolie.tinte
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { fragtGeben = false }) {
                    Text(stringResource(R.string.abbrechen), color = Magnolie.braun)
                }
            }
        )
    }
}

/**
 * Ein Datumsfeld ohne Kalenderdialog: drei Schnellwahlen und ein Feld für
 * `JJJJ-MM-TT`. Das reicht für Aufgaben und bleibt beim Papierbild.
 */
@Composable
private fun Datumfeld(wert: String, beiAenderung: (String) -> Unit) {
    val form = remember { SimpleDateFormat("yyyy-MM-dd", Locale.ROOT) }
    fun inTagen(tage: Int): String {
        val k = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, tage) }
        return form.format(k.time)
    }
    Column {
        Schreibfeld(
            wert = wert,
            beschriftung = stringResource(R.string.aufgabe_faellig),
            beiAenderung = beiAenderung
        )
        Row(
            Modifier.padding(top = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Papierknopf(stringResource(R.string.aufgabe_heute_kopf)) { beiAenderung(inTagen(0)) }
            Papierknopf(stringResource(R.string.aufgabe_morgen_kopf)) { beiAenderung(inTagen(1)) }
            Papierknopf(stringResource(R.string.aufgabe_plus_sieben_tage)) {
                beiAenderung(inTagen(7))
            }
            Papierknopf(stringResource(R.string.aufgabe_ohne_kopf)) { beiAenderung("") }
        }
    }
}

private fun erinnerungsUhrzeit(stunde: Int): String {
    val kalender = Calendar.getInstance().apply {
        set(Calendar.HOUR_OF_DAY, stunde)
        set(Calendar.MINUTE, 0)
    }
    return java.text.DateFormat.getTimeInstance(java.text.DateFormat.SHORT).format(kalender.time)
}
