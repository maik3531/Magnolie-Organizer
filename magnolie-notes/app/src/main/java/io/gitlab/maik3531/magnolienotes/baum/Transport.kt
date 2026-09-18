package io.gitlab.maik3531.magnolienotes.baum

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothSocket
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import java.io.ByteArrayOutputStream
import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.InputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.util.UUID

/**
 * Ein Weg, auf dem eine Baumnachricht zur Gegenstelle kommt. Die Nachrichten
 * selbst sind bei beiden Wegen dieselben; nur die Röhre ist eine andere.
 */
interface Transport : AutoCloseable {
    val bezeichnung: String
    /** Schickt eine Nutzlast an einen Baumpfad und liefert die Antwort. */
    fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int = 6000): JsonObject
    fun schliessen() {}
    override fun close() = schliessen()
}

/** Emitted only by the connect stage, never by response parsing or a reset socket. */
internal class KeineVerbindung(cause: Exception) : java.io.IOException(cause)

internal fun verbindungAbgelehnt(error: java.net.ConnectException): Boolean {
    val errno = (error.cause as? android.system.ErrnoException)?.errno
    if (errno != null) return errno == android.system.OsConstants.ECONNREFUSED
    // Android supplies errno; JVM sockets may expose only the localized OS text.
    val refused = runCatching { android.system.Os.strerror(android.system.OsConstants.ECONNREFUSED) }.getOrNull()
    return error.message in setOf("Connection refused", "Verbindungsaufbau abgelehnt") ||
        (!refused.isNullOrEmpty() && error.message == refused)
}

/**
 * Der Weg über WLAN: schlichtes HTTP auf Port 8737 über einen eigenen Socket.
 * So bleibt Androids HTTP-Klartexterlaubnis für alle anderen Ziele abgeschaltet.
 */
class WlanTransport(private val host: String, private val port: Int) : Transport {
    private val sperre = Any()
    private var beendet = false
    private var buchse: Socket? = null

    companion object {
        const val ANTWORT_MAX = 1024 * 1024
        private val FRISTEN = java.util.concurrent.ScheduledThreadPoolExecutor(1) { task ->
            Thread(task, "baum-wlan-frist").apply { isDaemon = true }
        }.apply { removeOnCancelPolicy = true }
    }

    override val bezeichnung: String get() = Netz.hostPortAnzeigen(host, port)

    override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject {
        val roh = Kanonisch.json.encodeToString(JsonObject.serializer(), nutzlast)
            .toByteArray(Charsets.UTF_8)
        return Socket().use { verbindung ->
            synchronized(sperre) {
                check(!beendet)
                check(buchse == null)
                buchse = verbindung
            }
            val frist = FRISTEN.schedule({ runCatching { verbindung.close() } },
                zeitgrenzeMs.coerceAtLeast(1).toLong(), java.util.concurrent.TimeUnit.MILLISECONDS)
            try {
            try {
                verbindung.connect(InetSocketAddress(host, port), zeitgrenzeMs)
            } catch (error: java.net.UnknownHostException) {
                throw KeineVerbindung(error)
            } catch (error: java.net.ConnectException) {
                if (verbindungAbgelehnt(error)) throw KeineVerbindung(error)
                throw error
            }
            verbindung.soTimeout = zeitgrenzeMs
            val hostKopf = if (host.contains(":")) "[$host]:$port" else "$host:$port"
            val kopf = "POST $pfad HTTP/1.1\r\nHost: $hostKopf\r\n" +
                "Content-Type: application/json\r\nContent-Length: ${roh.size}\r\n" +
                "Connection: close\r\n\r\n"
            verbindung.getOutputStream().apply {
                write(kopf.toByteArray(Charsets.US_ASCII))
                write(roh)
                flush()
            }

            val herein = BufferedInputStream(verbindung.getInputStream())
            val kopfBytes = liesKopf(herein)
            val zeilen = kopfBytes.toString(Charsets.ISO_8859_1).split("\r\n")
            val nummer = zeilen.firstOrNull()?.split(' ')?.getOrNull(1)?.toIntOrNull()
                ?: throw BaumFehler("Die Gegenstelle hat ungültig geantwortet.")
            val laengen = zeilen.drop(1).mapNotNull { zeile ->
                val teile = zeile.split(':', limit = 2)
                if (teile.size == 2 && teile[0].equals("Content-Length", true))
                    teile[1].trim().toLongOrNull() else null
            }
            if (laengen.size > 1 || laengen.singleOrNull()?.let { it < 0 || it > ANTWORT_MAX } == true) {
                throw BaumFehler("Die Antwort der Gegenstelle ist zu groß.")
            }
            val antwort = liesAntwort(herein, laengen.singleOrNull())
                .toString(Charsets.UTF_8)
            if (nummer !in 200..299) {
                throw BaumFehler(Netz.fehlertext(nummer, antwort))
            }
            if (antwort.isBlank()) throw BaumFehler("Die Gegenstelle hat nichts geantwortet.")
            Kanonisch.json.parseToJsonElement(antwort).jsonObject
            } finally {
                frist.cancel(false)
                synchronized(sperre) { if (buchse === verbindung) buchse = null }
            }
        }
    }

    override fun schliessen() {
        synchronized(sperre) {
            beendet = true
            runCatching { buchse?.close() }
            buchse = null
        }
    }

    private fun liesKopf(strom: InputStream): ByteArray {
        val kopf = ByteArrayOutputStream()
        var ende = 0
        while (ende != 4) {
            val zeichen = strom.read()
            if (zeichen < 0 || kopf.size() >= 64 * 1024) {
                throw BaumFehler("Die Gegenstelle hat ungültig geantwortet.")
            }
            kopf.write(zeichen)
            ende = when (zeichen) {
                '\r'.code -> if (ende == 0 || ende == 2) ende + 1 else 0
                '\n'.code -> if (ende == 1 || ende == 3) ende + 1 else 0
                else -> 0
            }
        }
        return kopf.toByteArray().dropLast(4).toByteArray()
    }

    private fun liesAntwort(strom: InputStream, erwartet: Long?): ByteArray {
        val antwort = ByteArrayOutputStream()
        val puffer = ByteArray(8192)
        while (erwartet == null || antwort.size().toLong() < erwartet) {
            val rest = erwartet?.minus(antwort.size())?.coerceAtMost(puffer.size.toLong())
                ?.toInt() ?: puffer.size
            val gelesen = strom.read(puffer, 0, rest)
            if (gelesen < 0) break
            if (gelesen > ANTWORT_MAX - antwort.size()) {
                throw BaumFehler("Die Antwort der Gegenstelle ist zu groß.")
            }
            antwort.write(puffer, 0, gelesen)
        }
        if (erwartet != null && antwort.size().toLong() != erwartet) {
            throw BaumFehler("Die Gegenstelle hat ungültig geantwortet.")
        }
        return antwort.toByteArray()
    }
}

/**
 * Der Weg über Bluetooth-RFCOMM. Die Nachricht ist dieselbe; statt HTTP
 * trägt ein Rahmen aus vier Längenbytes den Pfad und die Nutzlast.
 *
 * Der Organizer registriert dieselbe Dienstkennung bei BlueZ. Beide Wege
 * enden dadurch im identischen verschlüsselten Magnolienbaum-Handler.
 */
class BluetoothTransport(private val mac: String) : Transport {

    override val bezeichnung: String get() = mac

    private var buchse: BluetoothSocket? = null
    private val sperre = Any()
    private var beendet = false

    override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject {
        val adapter = BluetoothAdapter.getDefaultAdapter()
            ?: throw BaumFehler("Dieses Gerät hat kein Bluetooth.")
        if (!adapter.isEnabled) throw BaumFehler("Bluetooth ist ausgeschaltet.")
        val geraet = try {
            adapter.getRemoteDevice(mac)
        } catch (fehler: IllegalArgumentException) {
            throw BaumFehler("Die Bluetooth-Adresse ist ungültig.")
        }
        @Suppress("MissingPermission")
        val offen = geraet.createRfcommSocketToServiceRecord(DIENST_UUID)
        synchronized(sperre) {
            if (beendet) { offen.close(); throw java.io.IOException() }
            buchse = offen
        }
        val frist = FRISTEN.schedule({ runCatching { offen.close() } },
            zeitgrenzeMs.coerceAtLeast(1).toLong(), java.util.concurrent.TimeUnit.MILLISECONDS)
        try {
            @Suppress("MissingPermission")
            offen.connect()
            val hinaus = DataOutputStream(offen.outputStream)
            val herein = DataInputStream(offen.inputStream)
            schreibeRahmen(hinaus, pfad, nutzlast)
            return lieRahmen(herein)
        } finally {
            frist.cancel(false)
            runCatching { offen.close() }
            synchronized(sperre) { if (buchse === offen) buchse = null }
        }
    }

    override fun schliessen() {
        synchronized(sperre) {
            beendet = true
            runCatching { buchse?.close() }
            buchse = null
        }
    }

    companion object {
        /** Feste Dienstkennung des Magnolienbaums über RFCOMM. */
        private val FRISTEN = java.util.concurrent.ScheduledThreadPoolExecutor(1) { runnable ->
            Thread(runnable, "baum-bluetooth-frist").apply { isDaemon = true }
        }.apply { removeOnCancelPolicy = true }
        val DIENST_UUID: UUID = UUID.fromString("6d61676e-6f6c-6965-6e62-61756d383733")
        const val RAHMEN_MAX = 40 * 1024 * 1024

        fun schreibeRahmen(hinaus: DataOutputStream, pfad: String, nutzlast: JsonObject) {
            val umschlag = kotlinx.serialization.json.buildJsonObject {
                put("pfad", kotlinx.serialization.json.JsonPrimitive(pfad))
                put("nutzlast", nutzlast)
            }
            val roh = Kanonisch.json
                .encodeToString(JsonObject.serializer(), umschlag)
                .toByteArray(Charsets.UTF_8)
            if (roh.size > RAHMEN_MAX) throw BaumFehler("Die Nachricht ist zu groß für Bluetooth.")
            hinaus.writeInt(roh.size)
            hinaus.write(roh)
            hinaus.flush()
        }

        fun lieRahmen(herein: DataInputStream): JsonObject {
            val laenge = herein.readInt()
            if (laenge <= 0 || laenge > RAHMEN_MAX) throw BaumFehler("Der Bluetooth-Rahmen ist ungültig.")
            val roh = ByteArray(laenge)
            herein.readFully(roh)
            return Kanonisch.json.parseToJsonElement(String(roh, Charsets.UTF_8)).jsonObject
        }
    }
}

/** Kleine Netzhelfer, die dem Organizer entsprechen. */
object Netz {
    const val PORT = 8737

    fun url(host: String, port: Int, pfad: String): String {
        val gerahmt = if (host.contains(":")) "[" + host.replace("%", "%25") + "]" else host
        return "http://$gerahmt:$port$pfad"
    }

    fun hostPortAnzeigen(host: String, port: Int): String =
        if (host.contains(":")) "[$host]:$port" else "$host:$port"

    fun fehlertext(nummer: Int, koerper: String): String {
        val grund = runCatching {
            val feld = Kanonisch.json.parseToJsonElement(koerper).jsonObject["fehler"]
            (feld as? kotlinx.serialization.json.JsonPrimitive)?.content
        }.getOrNull()
        return when {
            !grund.isNullOrBlank() -> grund
            nummer == 503 -> "Der Magnolienbaum ist am Organizer ausgeschaltet."
            nummer == 403 -> "Die Gegenstelle hat den Zweig nicht anerkannt."
            nummer == 429 -> "Zu viele Anfragen – kurz warten."
            else -> "Die Gegenstelle antwortete mit $nummer."
        }
    }

    /** Die eigene Adresse im lokalen Netz, für Paarungsdateien und Anzeige. */
    fun eigeneAdresse(): String {
        val alle = mutableListOf<String>()
        try {
            val schnittstellen = java.net.NetworkInterface.getNetworkInterfaces()
            while (schnittstellen.hasMoreElements()) {
                val schnittstelle = schnittstellen.nextElement()
                if (!schnittstelle.isUp || schnittstelle.isLoopback) continue
                for (adresse in schnittstelle.inetAddresses) {
                    if (adresse.isLoopbackAddress || adresse.isLinkLocalAddress ||
                        adresse.isAnyLocalAddress || adresse.isMulticastAddress
                    ) continue
                    alle += adresse.hostAddress?.substringBefore('%').orEmpty()
                }
            }
        } catch (fehler: Exception) {
            // Ohne Netzliste bleibt nur die leere Rückgabe.
        }
        val gefiltert = alle.filter { it.isNotBlank() }
        return gefiltert.firstOrNull { it.count { z -> z == '.' } == 3 }
            ?: gefiltert.firstOrNull().orEmpty()
    }

    fun istErreichbar(host: String, zeitgrenzeMs: Int = 1200): Boolean = try {
        InetAddress.getByName(host).isReachable(zeitgrenzeMs)
    } catch (fehler: Exception) {
        false
    }
}
