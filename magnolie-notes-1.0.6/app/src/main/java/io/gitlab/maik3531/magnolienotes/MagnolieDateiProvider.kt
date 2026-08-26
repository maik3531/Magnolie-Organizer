package io.gitlab.maik3531.magnolienotes

import android.net.Uri
import android.os.Looper
import android.os.ParcelFileDescriptor
import androidx.core.content.FileProvider
import java.io.FileNotFoundException
import kotlinx.coroutines.runBlocking

class MagnolieDateiProvider : FileProvider() {
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        val app = context?.applicationContext as? MagnolieApp
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
}
