package io.gitlab.maik3531.magnolienotes

import android.content.Context
import android.os.Build
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream
import java.io.OutputStreamWriter
import java.io.PrintWriter
import java.nio.charset.StandardCharsets
import java.time.Instant

internal data class AbsturzMetadaten(
    val zeitUtc: String,
    val appVersion: String,
    val androidVersion: String,
    val api: Int,
    val hersteller: String,
    val modell: String,
)

internal class BegrenzterStrom(
    private val ziel: OutputStream,
    private val maximum: Long,
) : OutputStream() {
    private var geschrieben = 0L

    override fun write(wert: Int) {
        if (geschrieben < maximum) {
            ziel.write(wert)
            geschrieben++
        }
    }

    override fun write(daten: ByteArray, offset: Int, laenge: Int) {
        val uebrig = (maximum - geschrieben).coerceAtLeast(0).coerceAtMost(laenge.toLong()).toInt()
        if (uebrig > 0) {
            ziel.write(daten, offset, uebrig)
            geschrieben += uebrig
        }
    }

    override fun flush() = ziel.flush()
}

internal class AbsturzHandler(
    private val ordner: File,
    private val metadaten: () -> AbsturzMetadaten,
    private val vorher: Thread.UncaughtExceptionHandler?,
) : Thread.UncaughtExceptionHandler {
    private val bearbeitung = ThreadLocal<Boolean>()

    override fun uncaughtException(faden: Thread, fehler: Throwable) {
        try {
            if (bearbeitung.get() != true) {
                bearbeitung.set(true)
                try {
                    schreibe(faden, fehler)
                } catch (_: Throwable) {
                    // Crash reporting must never replace the original Android crash path.
                }
            }
        } finally {
            try {
                if (vorher !== this) vorher?.uncaughtException(faden, fehler)
            } finally {
                bearbeitung.remove()
            }
        }
    }

    private fun schreibe(faden: Thread, fehler: Throwable) = synchronized(SCHREIBSPERRE) {
        check(ordner.isDirectory || ordner.mkdirs())
        val aktuell = File(ordner, DATEINAME)
        val alt = File(ordner, "$DATEINAME.old")
        if (aktuell.isFile) {
            if (alt.exists()) check(alt.delete())
            check(aktuell.renameTo(alt))
        }
        val daten = metadaten()
        FileOutputStream(aktuell, false).use { datei ->
            val begrenzt = BegrenzterStrom(datei, MAXIMALE_BYTES)
            PrintWriter(OutputStreamWriter(begrenzt, StandardCharsets.UTF_8)).use { ausgabe ->
                ausgabe.println("Magnolie Notes crash report")
                ausgabe.println("UTC timestamp: ${daten.zeitUtc}")
                ausgabe.println("App version: ${daten.appVersion}")
                ausgabe.println("Android: ${daten.androidVersion} (API ${daten.api})")
                ausgabe.println("Device: ${daten.hersteller} ${daten.modell}")
                ausgabe.println("Thread: ${faden.name}")
                ausgabe.println("Exception type: ${fehler.javaClass.name}")
                ausgabe.println("Exception message: ${fehler.message.orEmpty()}")
                ausgabe.println("Stack trace and cause chain:")
                fehler.printStackTrace(ausgabe)
            }
            datei.fd.sync()
        }
    }

    companion object {
        internal const val DATEINAME = "magnolie-crash.txt"
        internal const val MAXIMALE_BYTES = 1024L * 1024L
        private val SCHREIBSPERRE = Any()
    }
}

object Absturzberichte {
    private const val ORDNER = "diagnostics"

    @Synchronized
    fun installieren(context: Context) {
        if (Thread.getDefaultUncaughtExceptionHandler() is AbsturzHandler) return
        val vorher = Thread.getDefaultUncaughtExceptionHandler()
            ?: Thread.currentThread().uncaughtExceptionHandler
        Thread.setDefaultUncaughtExceptionHandler(AbsturzHandler(File(context.filesDir, ORDNER), {
            AbsturzMetadaten(
                zeitUtc = Instant.now().toString(),
                appVersion = BuildConfig.VERSION_NAME,
                androidVersion = Build.VERSION.RELEASE.orEmpty(),
                api = Build.VERSION.SDK_INT,
                hersteller = Build.MANUFACTURER.orEmpty(),
                modell = Build.MODEL.orEmpty(),
            )
        }, vorher))
    }

    fun bericht(context: Context): File? {
        val ordner = File(context.filesDir, ORDNER)
        return listOf(
            File(ordner, AbsturzHandler.DATEINAME),
            File(ordner, "${AbsturzHandler.DATEINAME}.old"),
        ).firstOrNull(File::isFile)
    }
}
