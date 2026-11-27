package io.gitlab.maik3531.magnolienotes

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.AnhangPruefung
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException

/** Dekodiert einen geprüften Anhang ausschließlich in den internen Freigabecache. */
object AnhangDatei {
    const val DATA_URL_MAX = 12_000_000
    const val ROH_MAX = 8 * 1024 * 1024

    data class Inhalt(val bytes: ByteArray, val mime: String, val endung: String)

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

    private fun vorbereiten(context: Context, anhang: Anhang): Intent? {
        val inhalt = dekodieren(anhang) ?: return null
        val ordner = File(context.cacheDir, "anhaenge").apply { mkdirs() }
        ordner.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > 24 * 3600_000L }
            ?.forEach { it.delete() }
        val datei = File(ordner, anhang.id.filter(Char::isLetterOrDigit).take(64).ifBlank { "anhang" } + ".${inhalt.endung}")
        val neben = File.createTempFile("anhang-", ".neu", ordner)
        try {
            neben.writeBytes(inhalt.bytes)
            if (!neben.renameTo(datei)) return null
        } finally {
            neben.delete()
        }
        val uri = FileProvider.getUriForFile(context, context.packageName + ".dateien", datei)
        return Intent(Intent.ACTION_VIEW).setDataAndType(uri, inhalt.mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
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

    suspend fun oeffnen(context: Context, anhang: Anhang): Boolean {
        return try {
            val intent = withContext(Dispatchers.IO) { vorbereiten(context, anhang) } ?: return false
            withContext(Dispatchers.Main.immediate) {
                context.startActivity(intent)
                true
            }
        } catch (_: IOException) {
            false
        } catch (_: IllegalArgumentException) {
            false
        } catch (_: SecurityException) {
            false
        } catch (_: ActivityNotFoundException) {
            false
        }
    }
}
