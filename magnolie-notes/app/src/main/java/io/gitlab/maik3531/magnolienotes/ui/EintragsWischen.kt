package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.semantics.Role
import io.gitlab.maik3531.magnolienotes.R

enum class WischAktion { KEINE, LOESCHEN, ABGLEICHEN }
data class WischAnzeige(val aktiv: Boolean = true, val links: WischAktion = WischAktion.ABGLEICHEN,
                       val rechts: WischAktion = WischAktion.LOESCHEN)

internal class WischEinstellungen(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("magnolie_swipe_view", Context.MODE_PRIVATE)
    fun lesen() = WischAnzeige(prefs.getBoolean("enabled", true),
        WischAktion.entries.firstOrNull { it.name == prefs.getString("left", null) } ?: WischAktion.ABGLEICHEN,
        WischAktion.entries.firstOrNull { it.name == prefs.getString("right", null) } ?: WischAktion.LOESCHEN)
    fun speichern(value: WischAnzeige) {
        check(prefs.edit().putBoolean("enabled", value.aktiv).putString("left", value.links.name)
            .putString("right", value.rechts.name).commit()) { "swipe_preferences_unavailable" }
    }
}

@Composable internal fun wischText(action: WischAktion) = stringResource(when (action) {
    WischAktion.KEINE -> R.string.wischen_keine
    WischAktion.LOESCHEN -> R.string.loeschen
    WischAktion.ABGLEICHEN -> R.string.wischen_abgleichen
})

/** Physical left/right choices are retained in RTL layouts; partial swipes never dispatch. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable internal fun EintragsWischen(anzeige: WischAnzeige, beiAktion: (WischAktion) -> Unit,
                                        abgleichMoeglich: () -> Boolean = { true },
                                        inhalt: @Composable () -> Unit) {
    val rtl = LocalLayoutDirection.current == LayoutDirection.Rtl
    val latestRtl by rememberUpdatedState(rtl)
    val latestAction by rememberUpdatedState(beiAktion)
    val latestSettings by rememberUpdatedState(anzeige)
    val latestSyncAvailable by rememberUpdatedState(abgleichMoeglich)
    fun action(value: SwipeToDismissBoxValue): WischAktion {
        val chosen = if (!latestSettings.aktiv) WischAktion.KEINE else when (value) {
            SwipeToDismissBoxValue.StartToEnd -> if (latestRtl) latestSettings.links else latestSettings.rechts
            SwipeToDismissBoxValue.EndToStart -> if (latestRtl) latestSettings.rechts else latestSettings.links
            SwipeToDismissBoxValue.Settled -> WischAktion.KEINE
        }
        return if (chosen == WischAktion.ABGLEICHEN && !latestSyncAvailable()) WischAktion.KEINE else chosen
    }
    val state = rememberSwipeToDismissBoxState(confirmValueChange = { value ->
        val chosen = action(value)
        if (chosen != WischAktion.KEINE) latestAction(chosen)
        false // The row always returns; deletion is a separate confirmed operation.
    }, positionalThreshold = { width -> width * .45f })
    SwipeToDismissBox(state = state,
        enableDismissFromStartToEnd = action(SwipeToDismissBoxValue.StartToEnd) != WischAktion.KEINE,
        enableDismissFromEndToStart = action(SwipeToDismissBoxValue.EndToStart) != WischAktion.KEINE,
        backgroundContent = {
            val chosen = action(state.dismissDirection)
            Box(Modifier.fillMaxSize().background(Magnolie.papier).padding(horizontal = 20.dp),
                contentAlignment = if (state.dismissDirection == SwipeToDismissBoxValue.StartToEnd) Alignment.CenterStart else Alignment.CenterEnd) {
                if (chosen != WischAktion.KEINE) Text(wischText(chosen), color = if (chosen == WischAktion.LOESCHEN) Magnolie.rot else Magnolie.braun)
            }
        }) { Box(Modifier.background(Magnolie.papier)) { inhalt() } }
}

@Composable internal fun WischOptionen(value: WischAnzeige, beiAenderung: (WischAnzeige) -> Unit) {
    var direction by remember { mutableStateOf<Boolean?>(null) }
    direction?.let { left ->
        AlertDialog(onDismissRequest = { direction = null }, title = { Text(stringResource(if (left) R.string.wischen_links else R.string.wischen_rechts)) },
            text = { Column { WischAktion.entries.forEach { action ->
                Papierknopf(wischText(action), Modifier.fillMaxWidth()) {
                    beiAenderung(if (left) value.copy(links = action) else value.copy(rechts = action)); direction = null
                }
            } } }, confirmButton = { Papierknopf(stringResource(R.string.abbrechen)) { direction = null } })
    }
    Abschnitt(stringResource(R.string.wischen_titel), hinweis = stringResource(R.string.wischen_hinweis)) {
        Row(Modifier.fillMaxWidth().toggleable(value.aktiv, role = Role.Checkbox,
            onValueChange = { beiAenderung(value.copy(aktiv = it)) }), verticalAlignment = Alignment.CenterVertically) {
            Checkbox(value.aktiv, null)
            Text(stringResource(R.string.wischen_aktiv))
        }
        Papierknopf(stringResource(R.string.wischen_links) + ": " + wischText(value.links), Modifier.fillMaxWidth()) { direction = true }
        Papierknopf(stringResource(R.string.wischen_rechts) + ": " + wischText(value.rechts), Modifier.fillMaxWidth()) { direction = false }
    }
}

@Composable internal fun EintragLoeschFrage(titel: String, beiLoeschen: () -> Boolean, beiSchliessen: () -> Unit) {
    val context = LocalContext.current
    AlertDialog(onDismissRequest = beiSchliessen, containerColor = Magnolie.papier,
        title = { Text(stringResource(R.string.loeschen), fontFamily = FontFamily.Serif) },
        text = { Text(titel + "\n\n" + stringResource(R.string.wischen_bestaetigung)) },
        confirmButton = { TextButton(onClick = {
            val result = runCatching(beiLoeschen)
            if (result.getOrNull() != true) android.widget.Toast.makeText(context,
                if (result.isFailure) R.string.wischen_fehler else R.string.wischen_geaendert, android.widget.Toast.LENGTH_LONG).show()
            beiSchliessen()
        }) { Text(stringResource(R.string.loeschen), color = Magnolie.rot) } },
        dismissButton = { TextButton(onClick = beiSchliessen) { Text(stringResource(R.string.abbrechen), color = Magnolie.braun) } })
}
