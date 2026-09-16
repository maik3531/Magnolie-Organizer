package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.IconButton
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.activity.compose.BackHandler
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.Notizbuch
import io.gitlab.maik3531.magnolienotes.daten.Anhang

data class AnhangEreignis(val notizId: String, val anhang: Anhang)

internal fun notizEditorKompakt(
    verfuegbareHoeheDp: Float,
    fontScale: Float,
    imeSichtbar: Boolean,
    anhangAnzahl: Int
): Boolean {
    if (imeSichtbar || fontScale > 1.15f || anhangAnzahl >= 2) return true
    val benoetigteHoehe = if (anhangAnzahl == 1) 620f else 540f
    return verfuegbareHoeheDp < benoetigteHoehe
}

/**
 * Das Notizblatt: alle Notizen nach Tag geordnet, jede mit ihrem Sinnbild,
 * ihrer Uhrzeit und der Herkunft.
 */
@Composable
fun NotizBlatt(
    notizen: List<Notiz>,
    notizbuecher: List<Notizbuch>,
    beiOeffnen: (Notiz) -> Unit,
    beiNeu: () -> Unit,
    modifier: Modifier = Modifier
) {
    var suche by remember { mutableStateOf("") }
    val gesucht = remember(notizen, suche) {
        if (suche.isBlank()) notizen else notizen.filter {
            it.titel.contains(suche, true) || it.text.contains(suche, true)
        }
    }
    // Neueste zuerst, nach Tagen zusammengefasst.
    val nachTagen = remember(gesucht) {
        gesucht.sortedByDescending { it.geaendert }
            .groupBy { Zeit.tagesschluessel(it.geaendert) }
            .toList()
    }
    val heute = stringResource(R.string.heute)
    val gestern = stringResource(R.string.gestern)

    Column(modifier.fillMaxSize().background(Magnolie.papier)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Box(Modifier.weight(1f)) {
                Schreibfeld(
                    wert = suche,
                    beschriftung = stringResource(R.string.notiz_suchen),
                    beiAenderung = { suche = it }
                )
            }
            Lederknopf(stringResource(R.string.notiz_neu), beiKlick = beiNeu)
        }

        if (notizen.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    stringResource(R.string.notiz_leer),
                    fontFamily = FontFamily.Serif,
                    fontSize = 15.sp,
                    color = Magnolie.braunHell,
                    modifier = Modifier.padding(36.dp)
                )
            }
            return@Column
        }

        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = 28.dp)
        ) {
            nachTagen.forEach { (_, tagesnotizen) ->
                val wann = tagesnotizen.first().geaendert
                item(key = "tag-" + Zeit.tagesschluessel(wann)) {
                    Row(
                        Modifier.fillMaxWidth()
                            .padding(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            Zeit.tagesueberschrift(wann, heute, gestern),
                            fontFamily = FontFamily.SansSerif,
                            fontWeight = FontWeight.Bold,
                            fontSize = 12.sp,
                            color = Magnolie.braun
                        )
                        Box(
                            Modifier.padding(start = 10.dp)
                                .weight(1f).height(1.dp).background(Magnolie.linie)
                        )
                    }
                }
                items(tagesnotizen, key = { it.id }) { notiz ->
                    Notizzeile(
                        notiz = notiz,
                        buchname = notizbuecher.firstOrNull { it.id == notiz.notizbuchId }?.name.orEmpty(),
                        beiKlick = { beiOeffnen(notiz) }
                    )
                }
            }
        }
    }
}

@Composable
private fun Notizzeile(notiz: Notiz, buchname: String, beiKlick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = beiKlick)
            .padding(horizontal = 14.dp, vertical = 9.dp),
        verticalAlignment = Alignment.Top
    ) {
        Sinnbild(notiz.symbol)
        Column(Modifier.padding(start = 12.dp).weight(1f)) {
            Text(
                notiz.anzeigeTitel.ifBlank { notiz.vorschau.take(60) },
                fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.SemiBold,
                fontSize = 16.sp,
                color = Magnolie.tinte,
                maxLines = 1
            )
            if (notiz.vorschau.isNotBlank()) {
                Text(
                    notiz.vorschau,
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp,
                    lineHeight = 17.sp,
                    color = Magnolie.braunHell,
                    maxLines = 2,
                    modifier = Modifier.padding(top = 2.dp)
                )
            }
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    Zeit.uhrzeit(notiz.geaendert),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    color = Magnolie.goldDunkel
                )
                if (buchname.isNotBlank()) {
                    Text(
                        buchname,
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 11.sp,
                        color = Magnolie.braunHell
                    )
                }
                if (notiz.baumFreigabe != null) {
                    Text(
                        stringResource(R.string.notiz_magnolienbaum),
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

/**
 * Das Schreibblatt einer einzelnen Notiz. Überschrift, Wortlaut, Sinnbild –
 * und der Weg zum Magnolienbaum.
 */
@Composable
@OptIn(ExperimentalLayoutApi::class)
fun NotizEditor(
    notiz: Notiz,
    partnernamen: List<Pair<String, String>>,
    beiSichern: (Notiz) -> Unit,
    beiEntwurf: (Notiz) -> Unit,
    speichert: Boolean,
    beiLoeschen: () -> Unit,
    beiTeilen: (List<String>) -> Unit,
    beiAnhangOeffnen: (Anhang) -> Unit,
    beiAnhangSpeichern: (Anhang) -> Unit,
    beiAnhangHinzufuegen: () -> Unit,
    anhangEreignis: AnhangEreignis?,
    beiAnhangEreignisVerbraucht: () -> Unit,
    beiAnhaengeAenderung: (List<Anhang>) -> Unit,
    modifier: Modifier = Modifier
) {
    val titel = notiz.titel
    val text = notiz.text
    val symbol = notiz.symbol
    val anhaenge = notiz.anhaenge
    var fragtLoeschen by remember { mutableStateOf(false) }
    var fragtTeilen by remember { mutableStateOf(false) }
    var anhangAktion by remember { mutableStateOf<Anhang?>(null) }

    LaunchedEffect(anhangEreignis) {
        val ereignis = anhangEreignis ?: return@LaunchedEffect
        if (ereignis.notizId == notiz.id && anhaenge.none { it.id == ereignis.anhang.id }) {
            beiAnhaengeAenderung(anhaenge + ereignis.anhang)
        }
        beiAnhangEreignisVerbraucht()
    }

    fun sichern() { if (!speichert) beiSichern(notiz) }
    BackHandler { sichern() }

    Column(modifier.fillMaxSize().background(Magnolie.papier)) {
        Einband(titel.ifBlank { stringResource(R.string.notiz_neu) }) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Rundknopf("‹", beschreibung = stringResource(R.string.zurueck)) {
                    sichern()
                }
            }
        }

        BoxWithConstraints(
            Modifier.weight(1f).navigationBarsPadding().imePadding()
        ) {
            val density = LocalDensity.current
            val kompakt = notizEditorKompakt(
                verfuegbareHoeheDp = maxHeight.value,
                fontScale = density.fontScale,
                imeSichtbar = WindowInsets.ime.getBottom(density) > 0,
                anhangAnzahl = anhaenge.size
            )
            val scrollState = rememberScrollState()
            val scrollModifier = if (kompakt) {
                Modifier.verticalScroll(scrollState)
            } else Modifier
            val kompakteTextHoehe = (maxHeight - 28.dp).coerceAtLeast(220.dp)

            Column(
                Modifier.fillMaxSize().then(scrollModifier).padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
            Schreibfeld(
                wert = titel,
                beschriftung = stringResource(R.string.notiz_titel),
                beiAenderung = { beiEntwurf(notiz.copy(titel = it)) },
                aktiv = !speichert,
                serifen = true
            )

            if (anhaenge.isNotEmpty()) {
                Text(
                    stringResource(R.string.notiz_anhaenge, anhaenge.size),
                    fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.braunHell
                )
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(anhaenge, key = { it.id }) { anhang ->
                        Row(
                            Modifier.background(Magnolie.papierTief, RoundedCornerShape(8.dp))
                                .padding(4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Papierknopf(anhang.name.ifBlank {
                                stringResource(if (anhang.art == "pdf") R.string.notiz_pdf else R.string.notiz_bild)
                            }) { anhangAktion = anhang }
                            TextButton(enabled = !speichert, onClick = {
                                beiAnhaengeAenderung(anhaenge.filterNot { it.id == anhang.id })
                            }) {
                                Text(stringResource(R.string.notiz_anhang_entfernen), color = Magnolie.rot)
                            }
                        }
                    }
                }
            }
            Papierknopf(stringResource(R.string.notiz_anhang_hinzufuegen), aktiv = !speichert, beiKlick = beiAnhangHinzufuegen)
                Schreibfeld(
                    wert = text,
                    beschriftung = stringResource(R.string.notiz_text),
                    beiAenderung = { beiEntwurf(notiz.copy(text = it,
                        html = io.gitlab.maik3531.magnolienotes.baum.Nutzlast.textZuHtml(it))) },
                    aktiv = !speichert,
                    einzeilig = false,
                    serifen = true,
                    modifier = if (kompakt) {
                        Modifier.heightIn(
                            min = 220.dp,
                            max = kompakteTextHoehe
                        )
                    } else {
                        Modifier.weight(1f).heightIn(min = 220.dp)
                    }
                )

            Text(
                stringResource(R.string.notiz_symbol),
                fontFamily = FontFamily.SansSerif,
                fontSize = 12.sp,
                color = Magnolie.braunHell
            )
            LazyRow(
                Modifier.height(52.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                items(io.gitlab.maik3531.magnolienotes.daten.Symbol.alle) { art ->
                    val symbolName = sinnbildName(art)
                    val symbolBeschreibung = if (art == symbol) {
                        stringResource(R.string.semantik_ausgewaehlt, symbolName)
                    } else symbolName
                    IconButton(
                        onClick = { beiEntwurf(notiz.copy(symbol = art)) },
                        enabled = !speichert,
                        modifier = Modifier.size(48.dp)
                            .background(
                                if (art == symbol) Magnolie.gold.copy(alpha = 0.35f)
                                else androidx.compose.ui.graphics.Color.Transparent,
                                RoundedCornerShape(20.dp)
                            )
                    ) {
                        Sinnbild(art, groesse = 34.dp, modifier = Modifier.clearAndSetSemantics {
                                contentDescription = symbolBeschreibung
                                selected = art == symbol
                            })
                    }
                }
            }

            val angelegtText = stringResource(R.string.notiz_angelegt, Zeit.tagUndUhrzeit(
                if (notiz.angelegt > 0) notiz.angelegt else System.currentTimeMillis()
            ))
            val herkunftText = if (notiz.herkunft.isNotBlank()) {
                "  ·  " + stringResource(R.string.notiz_herkunft, notiz.herkunft)
            } else ""
            Text(
                angelegtText + herkunftText,
                fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp,
                color = Magnolie.braunHell
            )

                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Lederknopf(stringResource(R.string.sichern), aktiv = !speichert) { sichern() }
                    Papierknopf(
                        stringResource(R.string.notiz_teilen),
                        aktiv = partnernamen.isNotEmpty() && !speichert
                    ) { fragtTeilen = true }
                    Papierknopf(stringResource(R.string.loeschen), aktiv = !speichert) { fragtLoeschen = true }
                }
                if (speichert) androidx.compose.material3.LinearProgressIndicator(Modifier.fillMaxWidth())
            }
        }
    }

    anhangAktion?.let { anhang ->
        AlertDialog(
            onDismissRequest = { anhangAktion = null },
            containerColor = Magnolie.papier,
            title = {
                Text(
                    anhang.name.ifBlank {
                        stringResource(if (anhang.art == "pdf") R.string.notiz_pdf else R.string.notiz_bild)
                    },
                    fontFamily = FontFamily.Serif
                )
            },
            confirmButton = {
                TextButton(onClick = { anhangAktion = null; beiAnhangOeffnen(anhang) }) {
                    Text(stringResource(R.string.notiz_anhang_oeffnen), color = Magnolie.braun)
                }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = { anhangAktion = null; beiAnhangSpeichern(anhang) }) {
                        Text(stringResource(R.string.notiz_anhang_speichern), color = Magnolie.braun)
                    }
                    TextButton(onClick = { anhangAktion = null }) {
                        Text(stringResource(R.string.abbrechen), color = Magnolie.braun)
                    }
                }
            }
        )
    }

    if (fragtLoeschen) {
        AlertDialog(
            onDismissRequest = { fragtLoeschen = false },
            containerColor = Magnolie.papier,
            title = { Text(stringResource(R.string.notiz_loeschen), fontFamily = FontFamily.Serif) },
            text = { Text(stringResource(R.string.wirklich_loeschen)) },
            confirmButton = {
                TextButton(onClick = { fragtLoeschen = false; beiLoeschen() }) {
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

    if (fragtTeilen) {
        AlertDialog(
            onDismissRequest = { fragtTeilen = false },
            containerColor = Magnolie.papier,
            title = { Text(stringResource(R.string.notiz_teilen), fontFamily = FontFamily.Serif) },
            text = {
                Column {
                    partnernamen.forEach { (kennung, name) ->
                        Text(
                            stringResource(R.string.baum_teilen_frage, name),
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { fragtTeilen = false; beiTeilen(listOf(kennung)) }
                                .padding(vertical = 10.dp),
                            fontFamily = FontFamily.SansSerif,
                            fontSize = 14.sp,
                            color = Magnolie.tinte
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { fragtTeilen = false }) {
                    Text(stringResource(R.string.abbrechen), color = Magnolie.braun)
                }
            }
        )
    }
}
