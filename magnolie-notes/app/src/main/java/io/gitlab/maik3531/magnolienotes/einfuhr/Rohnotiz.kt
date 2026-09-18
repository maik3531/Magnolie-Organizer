package io.gitlab.maik3531.magnolienotes.einfuhr

import io.gitlab.maik3531.magnolienotes.baum.Nutzlast
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.Symbol

/**
 * Eine Notiz, wie sie aus einer Fremddatei purzelt – noch ohne Kennung und
 * ohne Sinnbild.
 */
data class Rohnotiz(
    val titel: String,
    val text: String,
    val html: String = "",
    val angelegt: Long = 0L,
    val geaendert: Long = 0L,
    val herkunft: String = "",
    val notizbuch: String = ""
) {
    val hatInhalt: Boolean get() = titel.isNotBlank() || text.isNotBlank() || html.isNotBlank()

    fun zuNotiz(notizbuchId: String): Notiz {
        val jetzt = System.currentTimeMillis()
        val wirklicherText = text.ifBlank {
            html.replace(Regex("<br\\s*/?>", RegexOption.IGNORE_CASE), "\n")
                .replace(Regex("</(?:div|p)>", RegexOption.IGNORE_CASE), "\n")
                .replace(Regex("<[^>]*>"), "")
                .let { entwirreEntitaeten(it) }
                .trim()
        }
        return Notiz(
            id = Ablage.kennung(),
            titel = titel.trim(),
            text = wirklicherText,
            html = if (html.isNotBlank()) Nutzlast.saeubereHtml(html) else Nutzlast.textZuHtml(wirklicherText),
            notizbuchId = notizbuchId,
            symbol = Symbol.raten(titel, wirklicherText),
            // Tag und Uhrzeit der Quelle bleiben erhalten, wo es sie gibt.
            angelegt = if (angelegt > 0) angelegt else (if (geaendert > 0) geaendert else jetzt),
            geaendert = if (geaendert > 0) geaendert else jetzt,
            herkunft = herkunft,
            einfuhrSchluessel = Ablage.einfuhrSchluessel(titel, wirklicherText)
        )
    }

    companion object {
        fun entwirreEntitaeten(text: String): String = text
            .replace("&nbsp;", " ")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
            .replace("&apos;", "'")
            .replace("&amp;", "&")
    }
}

/** Was eine Übernahme erbracht hat. */
data class Einfuhrergebnis(
    val gefunden: Int,
    val uebernommen: Int,
    val doppelt: Int,
    val quelle: String,
    val fehler: String = ""
)
