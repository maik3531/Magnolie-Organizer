package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.telefon.TelefonUiZustand
import kotlinx.serialization.json.JsonPrimitive

/** Direct shortcuts to the same actions exposed in device settings. */
@Composable
fun TelefonKopf(telefon: TelefonUiZustand, sync: () -> Unit, computer: (String?) -> Unit) {
    var opened by remember { mutableStateOf(false) }
    val syncName = stringResource(R.string.personal_sync_jetzt)
    val computerName = stringResource(R.string.telefon_rechner_hinzufuegen)
    val manual = telefon.sharedPreferencesValues?.get("auto_mode")?.let { it == JsonPrimitive("manual") }
        ?: !telefon.personalAutoWifi
    Row {
        if (manual && telefon.peer?.own_device == true) IconButton(onClick = sync,
            enabled = telefon.peer.remote_own_device, modifier = Modifier.semantics { contentDescription = syncName }) {
            Canvas(Modifier.size(24.dp)) {
                val colour = Magnolie.gold
                val line = size.width / 14
                drawArc(colour, 35f, 270f, false, Offset(size.width * .17f, size.height * .17f), size * .66f, style = Stroke(line, cap = StrokeCap.Round))
                drawLine(colour, Offset(size.width * .78f, size.height * .2f), Offset(size.width * .78f, size.height * .42f), line)
                drawLine(colour, Offset(size.width * .78f, size.height * .42f), Offset(size.width * .57f, size.height * .4f), line)
            }
        }
        Box {
            IconButton(onClick = { opened = !opened }, modifier = Modifier.semantics { contentDescription = computerName }) {
                Canvas(Modifier.size(25.dp)) {
                    val colour = Magnolie.gold; val line = size.width / 15
                    drawRect(colour, Offset(size.width * .17f, size.height * .15f), Size(size.width * .66f, size.height * .52f), style = Stroke(line))
                    drawLine(colour, Offset(size.width * .08f, size.height * .8f), Offset(size.width * .92f, size.height * .8f), line)
                }
            }
            DropdownMenu(expanded = opened, onDismissRequest = { opened = false }) {
                telefon.pairedComputers.forEach { peer ->
                    DropdownMenuItem(text = { Text((if (peer.device_id == telefon.peer?.device_id) "✓ " else "") + peer.display_name) },
                        onClick = { opened = false; computer(peer.device_id) })
                }
                DropdownMenuItem(text = { Text(computerName) }, onClick = { opened = false; computer(null) })
            }
        }
    }
}
