package io.gitlab.maik3531.magnolienotes

import android.content.Context
import android.net.Uri
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.AnhangPruefung
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.Base64

/** Liest ausschließlich geprüfte Bilder und PDF bis zur festen Rohdatengrenze. */
object AnhangLeser {
    const val ROH_MAX = 8 * 1024 * 1024

    enum class Fehler { LESEN, LEER, ZU_GROSS, UNGUELTIG }
    data class Ergebnis(val anhang: Anhang? = null, val fehler: Fehler? = null)

    fun lies(context: Context, quelle: Uri): Ergebnis {
        val mime = runCatching { context.contentResolver.getType(quelle) }.getOrNull()
        val name = runCatching { io.gitlab.maik3531.magnolienotes.einfuhr.Einfuhr.dateiname(context, quelle) }
            .getOrDefault("")
        val strom = runCatching { context.contentResolver.openInputStream(quelle) }.getOrNull()
            ?: return Ergebnis(fehler = Fehler.LESEN)
        return strom.use { lies(it, mime, name) }
    }

    fun lies(strom: InputStream, gemeldeterMime: String?, angezeigterName: String): Ergebnis {
        val roh = begrenztLesen(strom)
        if (roh == null) return Ergebnis(fehler = Fehler.ZU_GROSS)
        if (roh.isEmpty()) return Ergebnis(fehler = Fehler.LEER)
        val erkannt = mimeAusSignatur(roh) ?: return Ergebnis(fehler = Fehler.UNGUELTIG)
        val gemeldet = gemeldeterMime.orEmpty().trim().lowercase().substringBefore(';')
        val erlaubtOhneVergleich = gemeldet.isEmpty() || gemeldet == "application/octet-stream"
        val normalisiert = if (gemeldet == "image/jpg") "image/jpeg" else gemeldet
        if (!erlaubtOhneVergleich && normalisiert != erkannt) {
            return Ergebnis(fehler = Fehler.UNGUELTIG)
        }
        val name = angezeigterName.substringAfterLast('/').substringAfterLast('\\')
            .filterNot(Char::isISOControl).trim().take(180)
            .ifBlank { if (erkannt == "application/pdf") "document.pdf" else "image.${endung(erkannt)}" }
        val daten = "data:$erkannt;base64," + Base64.getEncoder().encodeToString(roh)
        return Ergebnis(Anhang(
            id = Ablage.kennung(),
            name = name,
            art = if (erkannt == "application/pdf") "pdf" else "image",
            daten = daten
        ))
    }

    internal fun begrenztLesen(strom: InputStream, max: Int = ROH_MAX): ByteArray? {
        val aus = ByteArrayOutputStream(minOf(max, 64 * 1024))
        val puffer = ByteArray(64 * 1024)
        var gesamt = 0
        while (true) {
            val gelesen = strom.read(puffer, 0, minOf(puffer.size, max + 1 - gesamt))
            if (gelesen < 0) break
            if (gelesen == 0) continue
            gesamt += gelesen
            if (gesamt > max) return null
            aus.write(puffer, 0, gelesen)
        }
        return aus.toByteArray()
    }

    internal fun mimeAusSignatur(roh: ByteArray): String? = AnhangPruefung.mime(roh)

    private fun endung(mime: String) = when (mime) {
        "image/jpeg" -> "jpg"
        "image/png" -> "png"
        "image/webp" -> "webp"
        else -> "gif"
    }
}
