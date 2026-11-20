package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.Constraints
import io.gitlab.maik3531.magnolienotes.R

/** Same measured search/button widths on both lists, including translated labels (Refs #719). */
@Composable
internal fun EintragSuchleiste(suche: String, beiSuche: (String) -> Unit, neu: String, beiNeu: () -> Unit) {
    val messen = rememberTextMeasurer()
    val stil = MaterialTheme.typography.labelLarge.copy(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
    val beschriftungen = listOf(stringResource(R.string.notiz_neu), stringResource(R.string.aufgabe_neu))
    val breitePx = maxOf(
        messen.measure(AnnotatedString(beschriftungen[0]), stil).size.width,
        messen.measure(AnnotatedString(beschriftungen[1]), stil).size.width
    )
    val knopfBreite = maxOf(64.dp, with(LocalDensity.current) { breitePx.toDp() } + 32.dp)
    // Leave room for both the 20sp input line and the 12sp label at enlarged
    // font scales; do not let different first-layout font rounding size a list.
    val feldHoehe = maxOf(56.dp, with(LocalDensity.current) { 32.sp.toDp() } + 24.dp)
    BoxWithConstraints(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
        val gestapelt = maxWidth < knopfBreite + 148.dp
        val dichte = LocalDensity.current
        val textBreite = with(dichte) { ((if (gestapelt) maxWidth else knopfBreite) - 32.dp).roundToPx().coerceAtLeast(1) }
        val textHoehe = beschriftungen.maxOf {
            messen.measure(AnnotatedString(it), stil, constraints = Constraints(maxWidth = textBreite)).size.height
        }
        val knopfHoehe = with(dichte) { textHoehe.toDp() } + 20.dp
        if (gestapelt) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Schreibfeld(suche, stringResource(R.string.notiz_suchen), beiSuche, modifier = Modifier.heightIn(min = feldHoehe))
                Lederknopf(neu, modifier = Modifier.fillMaxWidth().heightIn(min = knopfHoehe), beiKlick = beiNeu)
            }
        } else {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.weight(1f)) {
                    Schreibfeld(suche, stringResource(R.string.notiz_suchen), beiSuche, modifier = Modifier.heightIn(min = feldHoehe))
                }
                Lederknopf(neu, modifier = Modifier.width(knopfBreite).heightIn(min = knopfHoehe), beiKlick = beiNeu)
            }
        }
    }
}
