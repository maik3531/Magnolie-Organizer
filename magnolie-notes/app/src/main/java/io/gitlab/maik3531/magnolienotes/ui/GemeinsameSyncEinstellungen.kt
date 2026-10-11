package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Bestand
import io.gitlab.maik3531.magnolienotes.telefon.TelefonUiZustand
import kotlinx.serialization.json.*

internal fun gemeinsameSyncAnfangswerte(telefon: TelefonUiZustand, bestand: Bestand): Map<String, JsonElement> =
    telefon.sharedPreferencesValues ?: telefon.sharedPreferencesInitial ?: mapOf(
        "content_mode" to (telefon.peer?.personal_note_policy?.get("mode") ?: JsonPrimitive("phone_scope")),
        "auto_mode" to JsonPrimitive(if (telefon.personalAutoWifi) "wifi" else "manual"),
        "skip_deletions" to JsonPrimitive(!telefon.personalDeletionsEnabled),
        "custom_enabled" to JsonPrimitive(bestand.personalCustom.local?.get("enabled")?.jsonPrimitive?.booleanOrNull == true),
        "time_enabled" to JsonPrimitive(telefon.peer?.personal_time_policy?.get("enabled")?.jsonPrimitive?.booleanOrNull == true),
        "time_mode" to JsonPrimitive(if (telefon.peer?.personal_time_policy?.get("enabled")?.jsonPrimitive?.booleanOrNull == true) "two_way" else "phone_import"))

@Composable
internal fun GemeinsameSyncEinstellungen(telefon: TelefonUiZustand, bestand: Bestand, handlungen: Telefonhandlungen) {
    val values = gemeinsameSyncAnfangswerte(telefon, bestand)
    fun change(field: String, value: JsonElement) = handlungen.beiGemeinsameEinstellung(field, value, values)
    @Composable fun choice(field: String, title: String, options: List<Pair<String, String>>) {
        Text(title, fontWeight = FontWeight.Bold, color = Magnolie.braun)
        Column {
            options.forEach { (value, label) ->
                val selected = values[field] == JsonPrimitive(value)
                Row(Modifier.fillMaxWidth().selectable(selected, role = Role.RadioButton) { change(field, JsonPrimitive(value)) },
                    verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = selected, onClick = null)
                    Text(label, color = Magnolie.braun)
                }
            }
        }
    }
    choice("content_mode", stringResource(R.string.shared_sync_content), listOf(
        "phone_scope" to stringResource(R.string.shared_sync_notes_collection),
        "two_way" to stringResource(R.string.shared_sync_all_content),
        "phone_import" to stringResource(R.string.personal_note_import)))
    choice("auto_mode", stringResource(R.string.personal_sync_titel), listOf(
        "manual" to stringResource(R.string.shared_sync_manual),
        "wifi" to stringResource(R.string.personal_sync_auto_wlan)))
    if (values["content_mode"] != JsonPrimitive("phone_scope"))
        Schalterzeile(stringResource(R.string.personal_sync_skip_deletions), values["skip_deletions"] == JsonPrimitive(true)) { change("skip_deletions", JsonPrimitive(it)) }
    Schalterzeile(stringResource(R.string.personal_custom_optin), values["custom_enabled"] == JsonPrimitive(true)) { change("custom_enabled", JsonPrimitive(it)) }
    Schalterzeile(stringResource(R.string.zeit_titel), values["time_enabled"] == JsonPrimitive(true)) { change("time_enabled", JsonPrimitive(it)) }
    choice("time_mode", stringResource(R.string.shared_sync_time_direction), listOf(
        "phone_import" to stringResource(R.string.personal_note_import), "two_way" to stringResource(R.string.personal_note_two_way)))
}
