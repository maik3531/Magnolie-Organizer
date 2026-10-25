package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.material3.IconButton
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe

/** The same local Android print adapter as time reports, using the current draft. */
internal object EintragDrucken {
    private fun escape(value: String) = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")
    private fun document(title: String, text: String, extra: String = "") =
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><style>" +
            "body{font-family:serif;color:#222}h1{font-size:20pt;overflow-wrap:anywhere}.text{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12pt;line-height:1.4}img{max-width:100%;max-height:240mm;object-fit:contain}figure{break-inside:avoid}figcaption{font:10pt sans-serif}" +
            "</style><title>" + escape(title) + "</title></head><body><h1>" + escape(title) + "</h1><div class='text'>" + escape(text) + "</div>" + extra + "</body></html>"

    fun notizHtml(note: Notiz, fallbackTitle: String): String {
        val attachments = note.anhaenge.joinToString("") { item ->
            val image = item.art == "image" && Regex("data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=\\r\\n]+").matches(item.daten)
            "<figure>" + (if (image) "<img alt='' src='" + item.daten + "'>" else "") + "<figcaption>" + escape(item.name) + "</figcaption></figure>"
        }
        return document(note.anzeigeTitel.ifBlank { fallbackTitle }, note.text, attachments)
    }

    fun aufgabeHtml(task: Aufgabe, fallbackTitle: String, dueLabel: String, priorityLabel: String, statusLabel: String): String =
        document(task.anzeigeTitel.ifBlank { fallbackTitle }, task.notiz,
            "<p>" + escape(dueLabel) + ": " + escape(task.faellig) + "</p><p>" + escape(priorityLabel) + ": " + task.prio.coerceIn(1, 3) +
                "</p><p>" + escape(statusLabel) + ": " + (if (task.erledigt) "✓" else "☐") + "</p>")

    fun notiz(context: Context, note: Notiz) = open(context, notizHtml(note, context.getString(R.string.notiz_neu)), note.anzeigeTitel.ifBlank { context.getString(R.string.notiz_neu) })
    fun aufgabe(context: Context, task: Aufgabe) = open(context,
        aufgabeHtml(task, context.getString(R.string.aufgabe_neu), context.getString(R.string.aufgabe_faellig),
            context.getString(R.string.aufgabe_prio), context.getString(R.string.aufgabe_erledigt)),
        task.anzeigeTitel.ifBlank { context.getString(R.string.aufgabe_neu) })

    private fun open(context: Context, html: String, title: String) = ZeitDrucken.starten(context, html, title) {
        Toast.makeText(context, R.string.zeit_druck_fehler, Toast.LENGTH_LONG).show()
    }
}

@Composable
internal fun EintragDruckKnopf(aktiv: Boolean, beiKlick: () -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val automatic = remember(context) { DruckerEinstellungen.automatisch(context) }
    var available by remember { mutableStateOf(false) }
    LaunchedEffect(context, lifecycle, automatic) {
        if (automatic) lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            val search = DruckerSuche(context)
            try { search.starten(); search.erreichbar.collect { available = it } }
            finally { search.close(); available = false }
        }
    }
    if (automatic && !available) return
    val description = stringResource(R.string.zeit_drucken)
    IconButton(onClick = beiKlick, enabled = aktiv, modifier = Modifier.semantics { contentDescription = description }) {
        Canvas(Modifier.size(25.dp)) {
            val colour = Magnolie.gold; val line = size.width / 15
            drawRect(colour, Offset(size.width * .25f, size.height * .08f), Size(size.width * .5f, size.height * .32f), style = Stroke(line))
            drawRect(colour, Offset(size.width * .1f, size.height * .35f), Size(size.width * .8f, size.height * .4f), style = Stroke(line))
            drawRect(colour, Offset(size.width * .25f, size.height * .58f), Size(size.width * .5f, size.height * .34f), style = Stroke(line))
        }
    }
}
