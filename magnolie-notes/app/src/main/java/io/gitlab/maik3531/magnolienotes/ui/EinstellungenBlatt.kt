package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Text
import androidx.compose.material3.AlertDialog
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.gitlab.maik3531.magnolienotes.BuildConfig
import io.gitlab.maik3531.magnolienotes.Entwicklermodus
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R

@Composable
fun EinstellungenBlatt(zeiterfassungAn: Boolean, speichert: Boolean, beiZeiterfassung: (Boolean) -> Unit,
                       beiBlatt: (Int) -> Unit, beiRechten: () -> Unit, beiBenachrichtigungen: () -> Unit,
                       wischen: WischAnzeige, beiWischen: (WischAnzeige) -> Unit) {
    val context = LocalContext.current
    val developer = remember(context) { Entwicklermodus(context) }
    var druckerAutomatisch by remember { mutableStateOf(DruckerEinstellungen.automatisch(context)) }
    var developerEnabled by remember { mutableStateOf(developer.an) }
    var debugOpen by remember { mutableStateOf(false) }
    var wifi by remember { mutableStateOf(developer.wlan) }
    var report by remember { mutableStateOf<String?>(null) }
    var aboutOpen by remember { mutableStateOf(false) }
    val uriHandler = LocalUriHandler.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val versionClicks = remember(developer) { VersionsKlicks({ aboutOpen = true }, {
        developerEnabled = developer.versionAngeklickt()
    }) }
    DisposableEffect(versionClicks, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_PAUSE) versionClicks.abbrechen()
        }
        lifecycle.addObserver(observer)
        onDispose { versionClicks.abbrechen(); lifecycle.removeObserver(observer) }
    }
    if (aboutOpen) AlertDialog(onDismissRequest = { aboutOpen = false },
        title = { Text(stringResource(R.string.about_title)) },
        text = { Column(Modifier.verticalScroll(rememberScrollState())) {
            Text(stringResource(R.string.developer_version, BuildConfig.VERSION_NAME))
            Text(stringResource(R.string.about_part_of))
            Text(stringResource(R.string.about_author, stringResource(R.string.about_author_name)))
            NotesVersionsHinweis()
        } },
        confirmButton = { Papierknopf(stringResource(R.string.zurueck)) { aboutOpen = false } },
        dismissButton = { Papierknopf(stringResource(R.string.about_repository_label)) {
            versionClicks.abbrechen()
            uriHandler.openUri("https://github.com/maik3531/Magnolie-Organizer")
        } })
    if (report != null) AlertDialog(onDismissRequest = { report = null },
        title = { Text(stringResource(R.string.developer_show)) }, text = { Text(report!!) },
        confirmButton = { Papierknopf("OK") { report = null } })
    Column(Modifier.fillMaxSize().background(Magnolie.papier).verticalScroll(rememberScrollState())) {
        Abschnitt(stringResource(R.string.zeit_einstellungen)) {
            Papierknopf(stringResource(R.string.developer_version, BuildConfig.VERSION_NAME), Modifier.fillMaxWidth()) {
                versionClicks.klicken()
            }
            Papierknopf(stringResource(R.string.blatt_baum), Modifier.fillMaxWidth()) { beiBlatt(3) }
            Papierknopf(stringResource(R.string.blatt_einfuhr), Modifier.fillMaxWidth()) { beiBlatt(2) }
            if (developerEnabled) {
                Papierknopf(stringResource(R.string.developer_disable), Modifier.fillMaxWidth()) {
                    developer.deaktivieren(); developerEnabled = false; wifi = false; debugOpen = false; report = null
                }
                Papierknopf(stringResource(R.string.developer_options), Modifier.fillMaxWidth()) { debugOpen = !debugOpen }
            }
            if (developerEnabled && debugOpen) {
                Row(Modifier.fillMaxWidth().toggleable(wifi, role = Role.Checkbox, onValueChange = {
                    developer.wlanSetzen(it); wifi = it
                }), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Checkbox(wifi, null); Text(stringResource(R.string.developer_wifi))
                }
                if (wifi) Papierknopf(stringResource(R.string.developer_show), Modifier.fillMaxWidth()) { report = developer.bericht().toString() }
            }
            Papierknopf(stringResource(R.string.blatt_journal), Modifier.fillMaxWidth()) { beiBlatt(4) }
            Papierknopf(stringResource(R.string.zeit_systemrechte), Modifier.fillMaxWidth(), beiKlick = beiRechten)
            Papierknopf(stringResource(R.string.zeit_benachrichtigungen), Modifier.fillMaxWidth(), beiKlick = beiBenachrichtigungen)
        }
        ZeiterfassungsOptionen(zeiterfassungAn, speichert, beiZeiterfassung) { beiBlatt(6) }
        WischOptionen(wischen, beiWischen)
        Abschnitt(stringResource(R.string.zeit_drucken), hinweis = stringResource(R.string.drucker_symbol_hinweis)) {
            Row(Modifier.fillMaxWidth().toggleable(druckerAutomatisch, role = Role.Checkbox, onValueChange = { value ->
                runCatching { DruckerEinstellungen.automatisch(context, value); druckerAutomatisch = value }
                    .onFailure { android.widget.Toast.makeText(context, R.string.drucker_einstellung_fehler, android.widget.Toast.LENGTH_LONG).show() }
            }), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Checkbox(druckerAutomatisch, null); Text(stringResource(R.string.drucker_symbol_automatisch))
            }
        }
    }
}

@Composable
internal fun ZeiterfassungsOptionen(zeiterfassungAn: Boolean, speichert: Boolean,
                                   beiZeiterfassung: (Boolean) -> Unit, beiOeffnen: (() -> Unit)? = null) {
        Abschnitt(stringResource(R.string.zeit_titel), hinweis = stringResource(R.string.zeit_hinweis)) {
            Row(Modifier.fillMaxWidth().toggleable(zeiterfassungAn, enabled = !speichert,
                role = Role.Checkbox, onValueChange = beiZeiterfassung), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Checkbox(zeiterfassungAn, null, enabled = !speichert)
                Text(stringResource(R.string.zeit_aktiv))
            }
            if (beiOeffnen != null) Papierknopf(stringResource(R.string.zeit_titel), Modifier.fillMaxWidth(), beiKlick = beiOeffnen)
        }
}
