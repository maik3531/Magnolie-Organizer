package io.gitlab.maik3531.magnolienotes.baum

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothServerSocket
import android.bluetooth.BluetoothSocket
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Nimmt Baumnachrichten über Bluetooth-RFCOMM entgegen. Der Rahmen ist
 * absichtlich schlicht – vier Längenbytes, dann ein JSON-Umschlag mit `pfad`
 * und `nutzlast`. Was danach geschieht, macht derselbe [Server] wie über WLAN;
 * Kryptografie und Prüfungen sind also identisch.
 */
class BluetoothHorcher(private val server: Server) {

    private val laeuft = AtomicBoolean(false)
    private var buchse: BluetoothServerSocket? = null
    private val verbindungen = java.util.concurrent.ConcurrentHashMap.newKeySet<BluetoothSocket>()
    private val arbeiter = java.util.concurrent.ThreadPoolExecutor(2, 2, 0,
        java.util.concurrent.TimeUnit.MILLISECONDS, java.util.concurrent.ArrayBlockingQueue<Runnable>(2))
    private val fristen = java.util.concurrent.ScheduledThreadPoolExecutor(1).apply { removeOnCancelPolicy = true }

    @SuppressLint("MissingPermission")
    fun starten(): Boolean {
        if (laeuft.get()) return true
        val adapter = BluetoothAdapter.getDefaultAdapter() ?: return false
        if (!adapter.isEnabled) return false
        buchse = try {
            adapter.listenUsingRfcommWithServiceRecord(
                "Magnolienbaum", BluetoothTransport.DIENST_UUID
            )
        } catch (fehler: SecurityException) {
            return false
        } catch (fehler: Exception) {
            return false
        }
        laeuft.set(true)
        thread(name = "baum-bluetooth", isDaemon = true) { horchen() }
        return true
    }

    fun anhalten() {
        laeuft.set(false)
        runCatching { buchse?.close() }
        buchse = null
        verbindungen.forEach { runCatching { it.close() } }
        arbeiter.shutdownNow()
        fristen.shutdownNow()
    }

    private fun horchen() {
        while (laeuft.get()) {
            val verbindung = try {
                buchse?.accept() ?: break
            } catch (fehler: Exception) {
                break
            }
            verbindungen += verbindung
            var frist: java.util.concurrent.ScheduledFuture<*>? = null
            try {
                frist = fristen.schedule({ runCatching { verbindung.close() } }, 10, java.util.concurrent.TimeUnit.SECONDS)
                arbeiter.execute {
                    try { bedienen(verbindung) }
                    finally { frist?.cancel(false); verbindungen.remove(verbindung) }
                }
            } catch (_: java.util.concurrent.RejectedExecutionException) {
                frist?.cancel(false)
                verbindungen.remove(verbindung)
                runCatching { verbindung.close() }
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun bedienen(verbindung: BluetoothSocket) {
        try {
            val herein = DataInputStream(verbindung.inputStream)
            val hinaus = DataOutputStream(verbindung.outputStream)
            val umschlag = BluetoothTransport.lieRahmen(herein)
            val pfad = text(umschlag, "pfad")
            val nutzlast = umschlag["nutzlast"]?.jsonObject
                ?: throw BaumFehler("Der Bluetooth-Rahmen ist unvollständig.")
            // Die Quelle ist hier die Geräteadresse; sie bindet die FS-Sitzung.
            val quelle = try {
                verbindung.remoteDevice?.address.orEmpty()
            } catch (fehler: SecurityException) {
                ""
            }
            val (_, antwort) = server.behandeln(pfad, nutzlast, quelle)
            antworten(hinaus, antwort)
        } catch (fehler: Exception) {
            // Eine abgebrochene Bluetooth-Verbindung braucht keine Meldung.
        } finally {
            runCatching { verbindung.close() }
        }
    }

    private fun antworten(hinaus: DataOutputStream, antwort: JsonObject) {
        val roh = Kanonisch.json
            .encodeToString(JsonObject.serializer(), antwort)
            .toByteArray(Charsets.UTF_8)
        hinaus.writeInt(roh.size)
        hinaus.write(roh)
        hinaus.flush()
    }
}
