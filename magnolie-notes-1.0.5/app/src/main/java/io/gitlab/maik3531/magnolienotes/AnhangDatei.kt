package io.gitlab.maik3531.magnolienotes

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.AnhangPruefung
import java.io.File
import java.util.Base64

/** Dekodiert einen geprüften Anhang ausschließlich in den internen Freigabecache. */
object AnhangDatei {
    const val DATA_URL_MAX = 12_000_000
    const val ROH_MAX = 8 * 1024 * 1024

    data class Inhalt(val bytes: ByteArray, val mime: String, val endung: String)
    data class Geoeffnet(val datei: File, val mime: String)

    fun dekodieren(anhang: Anhang): Inhalt? {
        val geprueft = AnhangPruefung.dataUrl(anhang.daten) ?: return null
        val mime = geprueft.mime
        val endung = when (mime) {
            "application/pdf" -> "pdf"
            "image/jpeg" -> "jpg"
            "image/png" -> "png"
            "image/webp" -> "webp"
            "image/gif" -> "gif"
            else -> return null
        }
        return Inhalt(geprueft.bytes, mime, endung)
    }

    fun sichererName(anhang: Anhang, inhalt: Inhalt): String {
        val roh = anhang.name.substringAfterLast('/').substringAfterLast('\\')
            .filterNot(Char::isISOControl).trim()
        val basis = roh.substringBeforeLast('.', roh).trim().take(170)
            .ifBlank { if (inhalt.mime == "application/pdf") "document" else "image" }
        return "$basis.${inhalt.endung}"
    }

    fun vorbereiten(context: Context, anhang: Anhang): Geoeffnet? {
        val inhalt = dekodieren(anhang) ?: return null
        val ordner = File(context.cacheDir, "anhaenge").apply { mkdirs() }
        ordner.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > 24 * 3600_000L }
            ?.forEach { it.delete() }
        val datei = File(ordner, anhang.id.filter(Char::isLetterOrDigit).take(64).ifBlank { "anhang" } + ".${inhalt.endung}")
        val neben = File(ordner, datei.name + ".neu")
        neben.writeBytes(inhalt.bytes)
        if (!neben.renameTo(datei)) { neben.delete(); return null }
        return Geoeffnet(datei, inhalt.mime)
    }

    fun speichern(context: Context, ziel: Uri, anhang: Anhang): Boolean {
        val inhalt = dekodieren(anhang) ?: return false
        return runCatching {
            context.contentResolver.openOutputStream(ziel, "wt")?.use { strom ->
                strom.write(inhalt.bytes)
                strom.flush()
            } ?: return false
            true
        }.getOrDefault(false)
    }

    fun oeffnen(context: Context, anhang: Anhang): Boolean {
        val offen = vorbereiten(context, anhang) ?: return false
        val uri = FileProvider.getUriForFile(context, context.packageName + ".dateien", offen.datei)
        val intent = Intent(Intent.ACTION_VIEW).setDataAndType(uri, offen.mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        return runCatching { context.startActivity(intent); true }.getOrDefault(false)
    }
}
