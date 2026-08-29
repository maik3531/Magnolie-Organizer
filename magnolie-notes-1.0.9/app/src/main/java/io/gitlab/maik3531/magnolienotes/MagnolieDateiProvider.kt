package io.gitlab.maik3531.magnolienotes

import android.net.Uri
import android.os.Looper
import android.os.ParcelFileDescriptor
import androidx.core.content.FileProvider
import java.io.FileNotFoundException
import kotlinx.coroutines.runBlocking

class MagnolieDateiProvider : FileProvider() {
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        val zusammenhang = context ?: throw FileNotFoundException("Anwendung nicht bereit")
        if (diagnoseLesezugriff(uri, mode, zusammenhang.packageName + ".dateien")) {
            return super.openFile(uri, mode) ?: throw FileNotFoundException(uri.toString())
        }

        val app = zusammenhang.applicationContext as? MagnolieApp
            ?: throw FileNotFoundException("Anwendung nicht bereit")
        if (Looper.myLooper() == Looper.getMainLooper()) {
            if (app.startZustand.value != StartZustand.Bereit) {
                throw FileNotFoundException("Anwendung nicht bereit")
            }
        } else if (!runBlocking { app.awaitReady() }) {
            throw FileNotFoundException("Recovery erforderlich")
        }
        return super.openFile(uri, mode) ?: throw FileNotFoundException(uri.toString())
    }

    companion object {
        private const val DIAGNOSE_WURZEL = "diagnose"
        private val BERICHTE = setOf(
            AbsturzHandler.DATEINAME,
            "${AbsturzHandler.DATEINAME}.old",
        )

        internal fun diagnoseLesezugriff(uri: Uri, mode: String, authority: String): Boolean {
            val teile = uri.pathSegments
            if (teile.firstOrNull() != DIAGNOSE_WURZEL) return false
            val erlaubterBericht = teile.size == 2 && teile[1] in BERICHTE
            if (!erlaubterBericht || mode != "r" || uri.scheme != "content" ||
                uri.authority != authority
            ) {
                throw FileNotFoundException("Diagnosedatei nicht freigegeben")
            }
            return true
        }
    }
}
