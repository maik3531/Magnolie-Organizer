package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.res.stringResource
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand

@Composable
internal fun ZeitArtOptionen(stand: ZeiterfassungStand, speichert: Boolean, speichern: ZeitSpeichern) {
    val original = stand.defaultType
    var automatic by rememberSaveable(original) { mutableStateOf(original == null) }
    var name by rememberSaveable(original) { mutableStateOf(original.orEmpty()) }
    Abschnitt(stringResource(R.string.zeit_art_vorgabe)) {
        Papierknopf(stringResource(R.string.zeit_art_dienste), aktiv = !speichert, ausgewaehlt = automatic) { automatic = true }
        Papierknopf(stringResource(R.string.zeit_art_eigene), aktiv = !speichert, ausgewaehlt = !automatic) { automatic = false }
        if (!automatic) {
            Schreibfeld(name, stringResource(R.string.zeit_art_name), { name = it }, aktiv = !speichert)
            for (label in listOf(R.string.zeit_art_training, R.string.zeit_art_meeting)) {
                val text = stringResource(label)
                Papierknopf(text, aktiv = !speichert) { name = text }
            }
        }
        Text(stringResource(R.string.zeit_art_hinweis))
        val candidate = if (automatic) null else name
        Papierknopf(stringResource(R.string.sichern),
            aktiv = !speichert && (candidate == null || candidate.length <= 120) && candidate != original) {
            speichern({ it.changeDefaultType(original, candidate) }, {})
        }
    }
}
