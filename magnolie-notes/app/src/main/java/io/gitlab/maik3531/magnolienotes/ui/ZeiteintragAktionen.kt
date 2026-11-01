package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R

/** One shared row for editing and manual entries. Keep full labels and touch
 * targets; small screens/large fonts may scroll, never stack or truncate actions. */
@Composable
internal fun ZeiteintragAktionen(neu: Boolean, speichert: Boolean, beiSichern: () -> Unit,
    abbrechen: () -> Unit, beiLoeschen: () -> Unit) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        Lederknopf(stringResource(R.string.sichern), aktiv = !speichert, beiKlick = beiSichern)
        Papierknopf(stringResource(R.string.abbrechen), aktiv = !speichert, beiKlick = abbrechen)
        if (!neu) Papierknopf(stringResource(R.string.loeschen), aktiv = !speichert,
            destruktiv = true, beiKlick = beiLoeschen)
    }
}
