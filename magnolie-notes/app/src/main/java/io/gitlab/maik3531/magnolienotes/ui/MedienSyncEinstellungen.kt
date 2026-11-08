package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.telefon.TelefonUiZustand
import kotlinx.serialization.json.*

@Composable
private fun MedienCheckbox(label: String, checked: Boolean, enabled: Boolean = true, change: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().toggleable(checked, enabled = enabled, role = Role.Checkbox, onValueChange = change),
        verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked, onCheckedChange = null, enabled = enabled,
            colors = CheckboxDefaults.colors(checkedColor = Magnolie.goldDunkel, uncheckedColor = Magnolie.braunHell, checkmarkColor = Magnolie.papier))
        Text(label, color = Magnolie.braun, modifier = Modifier.weight(1f))
    }
}

@Composable
internal fun MedienSyncEinstellungen(telefon: TelefonUiZustand,
    beiAenderung: (String, JsonElement, String) -> Unit, beiBerechtigungen: () -> Unit, beiSynchronisieren: () -> Unit) {
    if (!telefon.mediaPreferencesSupported) return
    val values = telefon.mediaPreferencesValues ?: return
    var offen by remember(telefon.peer?.device_id, telefon.peer?.static_public) { mutableStateOf(false) }
    fun flag(field: String) = values[field] == JsonPrimitive(true)
    fun change(field: String, value: JsonElement) {
        val version = telefon.mediaPreferencesVersions[field] ?: return
        beiAenderung(field, value, version)
    }
    val enabled = flag("enabled")
    val activationLabel = stringResource(R.string.medien_sync_aktivieren)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Papierknopf((if (offen) "▾ " else "▸ ") + stringResource(R.string.medien_sync_titel), Modifier.weight(1f)) { offen = !offen }
        Checkbox(enabled, onCheckedChange = { change("enabled", JsonPrimitive(it)) },
            enabled = "enabled" in telefon.mediaPreferencesVersions,
            modifier = Modifier.padding(start = 16.dp).semantics { contentDescription = activationLabel },
            colors = CheckboxDefaults.colors(checkedColor = Magnolie.goldDunkel, uncheckedColor = Magnolie.braunHell, checkmarkColor = Magnolie.papier))
    }
    if (!offen) return
    @Composable fun checkbox(field: String, label: String, active: Boolean = enabled) =
        MedienCheckbox(label, flag(field), active && field in telefon.mediaPreferencesVersions) { change(field, JsonPrimitive(it)) }
    @Composable fun choice(field: String, label: String, options: List<Pair<String, String>>, available: Boolean = true) {
        var menu by remember(field) { mutableStateOf(false) }
        Text(label, fontWeight = FontWeight.Bold, color = Magnolie.braun)
        Box {
            Papierknopf(options.firstOrNull { values[field] == JsonPrimitive(it.first) }?.second ?: label,
                Modifier.fillMaxWidth(), aktiv = enabled && available && field in telefon.mediaPreferencesVersions) { menu = true }
            DropdownMenu(menu && enabled && available, onDismissRequest = { menu = false }) {
                options.forEach { (value, text) -> DropdownMenuItem(text = { Text(text) }, onClick = {
                    menu = false; change(field, JsonPrimitive(value))
                }) }
            }
        }
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(stringResource(R.string.medien_sync_zugriff), fontWeight = FontWeight.Bold, color = Magnolie.braun)
        Papierknopf("Android · " + stringResource(R.string.medien_sync_zugriff), Modifier.fillMaxWidth(), aktiv = enabled,
            beiKlick = beiBerechtigungen)
        Text(stringResource(R.string.medien_sync_einstellungen), fontWeight = FontWeight.Bold, color = Magnolie.braun)
        choice("collection_mode", stringResource(R.string.medien_sync_umfang), listOf(
            "phone_inventory" to stringResource(R.string.medien_sync_scope_phone), "entire_collection" to stringResource(R.string.medien_sync_scope_all),
            "import_only" to stringResource(R.string.medien_sync_scope_import)))
        choice("auto_mode", stringResource(R.string.medien_sync_modus), listOf(
            "manual" to stringResource(R.string.shared_sync_manual), "wifi" to stringResource(R.string.personal_sync_auto_wlan)))
        choice("direction", stringResource(R.string.medien_sync_richtung), listOf(
            "phone_to_pc" to stringResource(R.string.medien_sync_direction_import), "two_way" to stringResource(R.string.personal_note_two_way),
            "pc_to_phone" to stringResource(R.string.medien_sync_direction_export)), available = values["collection_mode"] != JsonPrimitive("import_only"))
        checkbox("photos_enabled", stringResource(R.string.medien_sync_fotos))
        checkbox("videos_enabled", stringResource(R.string.medien_sync_videos))
        checkbox("skip_deletions", stringResource(R.string.personal_sync_skip_deletions))
        if (!telefon.mediaPreferencesReady) Text(stringResource(R.string.baum_wartet), color = Magnolie.braunHell)
        if (telefon.mediaManualBusy) Text(stringResource(R.string.baum_wartet), color = Magnolie.braunHell)
        if (telefon.mediaManualState in setOf("held", "review")) Text(stringResource(R.string.media_recovery_uncertain), color = Magnolie.braunHell)
        Papierknopf(stringResource(R.string.personal_sync_jetzt), Modifier.fillMaxWidth(),
            aktiv = enabled && (flag("photos_enabled") || flag("videos_enabled")) && telefon.mediaPreferencesReady && !telefon.mediaManualBusy,
            beiKlick = beiSynchronisieren)
    }
}
