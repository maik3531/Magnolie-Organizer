package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.einfuhr.Einfuhrergebnis

/**
 * Das Übernahmeblatt. Es sagt offen, was geht und was nicht: die Datenbanken
 * von Samsung Notes und Keep liegen in deren Sandbox und sind für fremde Apps
 * verschlossen. Teilen und Exportdateien gehen dafür immer.
 */
@Composable
fun EinfuhrBlatt(
    ergebnis: Einfuhrergebnis?,
    laeuft: Boolean,
    beiDatei: () -> Unit,
    beiOrdner: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier.fillMaxSize().background(Magnolie.papier).verticalScroll(rememberScrollState())
    ) {
        Abschnitt(
            ueberschrift = stringResource(R.string.einfuhr_ueberschrift),
            hinweis = stringResource(R.string.einfuhr_erklaerung)
        ) {
            Text(
                stringResource(R.string.einfuhr_teilen_titel),
                fontFamily = FontFamily.SansSerif,
                fontSize = 13.sp,
                color = Magnolie.braun
            )
            Text(
                stringResource(R.string.einfuhr_teilen_text),
                fontFamily = FontFamily.SansSerif,
                fontSize = 12.sp,
                lineHeight = 18.sp,
                color = Magnolie.braunHell,
                modifier = Modifier.padding(top = 4.dp)
            )
        }

        Abschnitt(
            ueberschrift = stringResource(R.string.einfuhr_datei_titel),
            hinweis = stringResource(R.string.einfuhr_formate)
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Lederknopf(
                    stringResource(R.string.einfuhr_datei_knopf),
                    aktiv = !laeuft,
                    modifier = Modifier.fillMaxWidth(),
                    beiKlick = beiDatei
                )
                Papierknopf(
                    stringResource(R.string.einfuhr_ordner_knopf),
                    aktiv = !laeuft,
                    modifier = Modifier.fillMaxWidth(),
                    beiKlick = beiOrdner
                )
                if (laeuft) {
                    Text(
                        stringResource(R.string.einfuhr_laeuft),
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 12.sp,
                        color = Magnolie.braun
                    )
                }
                ergebnis?.let { bericht ->
                    val text = when {
                        bericht.fehler.isNotBlank() ->
                            stringResource(R.string.einfuhr_fehler, bericht.fehler)
                        bericht.gefunden == 0 -> stringResource(R.string.einfuhr_nichts)
                        else -> pluralStringResource(
                            R.plurals.einfuhr_ergebnis, bericht.uebernommen,
                            bericht.uebernommen, bericht.doppelt
                        )
                    }
                    Text(
                        text,
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 13.sp,
                        lineHeight = 19.sp,
                        color = if (bericht.fehler.isNotBlank()) Magnolie.rot else Magnolie.filz
                    )
                }
            }
        }

        Abschnitt(ueberschrift = stringResource(R.string.einfuhr_anleitung_titel)) {
            Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
                listOf(
                    R.string.einfuhr_anleitung_samsung,
                    R.string.einfuhr_anleitung_keep,
                    R.string.einfuhr_anleitung_evernote
                ).forEach { kennung ->
                    Text(
                        stringResource(kennung),
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 12.sp,
                        lineHeight = 18.sp,
                        color = Magnolie.tinte
                    )
                }
            }
        }

        Zwischenraum(20)
    }
}
