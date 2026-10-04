package io.gitlab.maik3531.magnolienotes.ui

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.WifiManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.ZeitEntwurf
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import io.gitlab.maik3531.magnolienotes.zeit.ZeitWlanScan

@Composable
fun ZeitWlanOptionen(stand: ZeiterfassungStand, speichert: Boolean, speichern: ZeitSpeichern) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val original = stand.wifi
    val locale = context.resources.configuration.locales[0]
    var enabled by rememberSaveable(original.enabled) { mutableStateOf(original.enabled) }
    var ssid by rememberSaveable(original.ssid) { mutableStateOf(original.ssid) }
    var cooldown by rememberSaveable(original.cooldownMinutes) { mutableStateOf("%d".format(locale, original.cooldownMinutes)) }
    var enabling by rememberSaveable { mutableStateOf(false) }
    var ready by remember { mutableStateOf(ZeitWlanScan.ready(context)) }
    var visible by remember { mutableStateOf(emptyList<ZeitWlanScan.Observation>()) }
    fun refresh() { ready = ZeitWlanScan.ready(context); visible = ZeitWlanScan.observations(context) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (enabling && ZeitWlanScan.permissionGranted(context)) enabled = true
        enabling = false
        refresh()
        ZeitWlanScan.request(context)
    }
    fun requestPermission() = permission.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
    DisposableEffect(context, owner) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) { refresh() }
        }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION).apply {
            addAction(WifiManager.WIFI_STATE_CHANGED_ACTION); addAction(android.location.LocationManager.MODE_CHANGED_ACTION)
        }, ContextCompat.RECEIVER_NOT_EXPORTED)
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_RESUME) refresh() }
        owner.lifecycle.addObserver(observer)
        onDispose { context.unregisterReceiver(receiver); owner.lifecycle.removeObserver(observer) }
    }
    val candidate = runCatching { original.copy(enabled = enabled, ssid = ssid,
        cooldownMinutes = ZeitEntwurf.digits(cooldown).trim().toInt()).validate() }.getOrNull()
    Abschnitt(stringResource(R.string.zeit_wlan_titel)) {
        val label = stringResource(R.string.zeit_wlan_titel)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, modifier = Modifier.weight(1f))
            Switch(checked = enabled, enabled = !speichert, onCheckedChange = {
                if (it && !ZeitWlanScan.permissionGranted(context)) { enabling = true; requestPermission() }
                else enabled = it
            }, modifier = Modifier.semantics { contentDescription = label })
        }
        Text(stringResource(R.string.zeit_wlan_hinweis))
        Schreibfeld(ssid, "SSID", { ssid = it }, aktiv = !speichert)
        Papierknopf(stringResource(R.string.zeit_wlan_suchen), aktiv = !speichert) {
            if (!ZeitWlanScan.permissionGranted(context)) { enabling = false; requestPermission() }
            else { refresh(); ZeitWlanScan.request(context) }
        }
        visible.forEach { item -> Papierknopf(item.ssid, aktiv = !speichert, ausgewaehlt = item.ssid == ssid) { ssid = item.ssid } }
        Schreibfeld(cooldown, stringResource(R.string.zeit_wlan_sperre), { cooldown = it }, aktiv = !speichert)
        Text(stringResource(R.string.zeit_wlan_neustart))
        Text(stringResource(R.string.zeit_wlan_rechte))
        if (!ready) {
            Papierknopf(stringResource(R.string.zeit_wlan_system)) { context.startActivity(Intent(Settings.ACTION_WIFI_SETTINGS)) }
            Papierknopf(stringResource(R.string.zeit_wlan_ort)) { context.startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)) }
        }
        val saveLabel = stringResource(R.string.sichern) + " " + stringResource(R.string.zeit_wlan_titel)
        Papierknopf(stringResource(R.string.sichern), modifier = Modifier.semantics { contentDescription = saveLabel },
            aktiv = !speichert && candidate != null &&
            candidate != original && (!enabled || ready)) {
            val chosen = candidate ?: return@Papierknopf
            speichern({ state ->
                check(state.wifi.enabled == original.enabled && state.wifi.ssid == original.ssid &&
                    state.wifi.cooldownMinutes == original.cooldownMinutes)
                state.copy(wifi = state.wifi.copy(enabled = chosen.enabled, ssid = chosen.ssid,
                    cooldownMinutes = chosen.cooldownMinutes)).validate()
            }, {})
        }
    }
}
