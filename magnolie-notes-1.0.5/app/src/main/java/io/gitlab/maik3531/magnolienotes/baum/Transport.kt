package io.gitlab.maik3531.magnolienotes.baum

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothSocket
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.Proxy
import java.net.URL
import java.util.UUID

/**
 * Ein Weg, auf dem eine Baumnachricht zur Gegenstelle kommt. Die Nachrichten
 * selbst sind bei beiden Wegen dieselben; nur die Röhre ist eine andere.
 */
interface Transport {
    val bezeichnung: String
    /** Schickt eine Nutzlast an einen Baumpfad und liefert die Antwort. */
    fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int = 6000): JsonObject
    fun schliessen() {}
}

/**
 * Der Weg über WLAN: schlichtes HTTP auf Port 8737, genau wie es der
 * Organizer erwartet. Kein Proxy, feste Länge, keine Weiterleitungen.
 */
class WlanTransport(private val host: String, private val port: Int) : Transport {

    companion object {
        const val ANTWORT_MAX = 1024 * 1024
    }

    override val bezeichnung: String get() = Netz.hostPortAnzeigen(host, port)

    override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject {
        val roh = Kanonisch.json.encodeToString(JsonObject.serializer(), nutzlast)
            .toByteArray(Charsets.UTF_8)
        val verbindung = URL(Netz.url(host, port, pfad)).openConnection(Proxy.NO_PROXY)
            as HttpURLConnection
        try {
            verbindung.requestMethod = "POST"
            verbindung.doOutput = true
            verbindung.instanceFollowRedirects = false
            verbindung.connectTimeout = zeitgrenzeMs
            verbindung.readTimeout = zeitgrenzeMs
            verbindung.setRequestProperty("Content-Type", "application/json")
            verbindung.setRequestProperty("Connection", "close")
            // Der Dienst weist Transfer-Encoding und Expect ausdrücklich ab.
            verbindung.setFixedLengthStreamingMode(roh.size)
            verbindung.outputStream.use { it.write(roh) }

            val nummer = verbindung.responseCode
            if (verbindung.contentLengthLong > ANTWORT_MAX) {
                throw BaumFehler("Die Antwort der Gegenstelle ist zu groß.")
            }
            val strom = if (nummer in 200..299) verbindung.inputStream else verbindung.errorStream
            val antwort = strom?.use { liesAntwort(it) }?.toString(Charsets.UTF_8).orEmpty()
            if (nummer !in 200..299) {
                throw BaumFehler(Netz.fehlertext(nummer, antwort))
            }
            if (antwort.isBlank()) throw BaumFehler("Die Gegenstelle hat nichts geantwortet.")
            return Kanonisch.json.parseToJsonElement(antwort).jsonObject
        } finally {
            verbindung.disconnect()
        }
    }

    private fun liesAntwort(strom: InputStream): ByteArray {
        val antwort = ByteArrayOutputStream()
        val puffer = ByteArray(8192)
        while (true) {
            val gelesen = strom.read(puffer)
            if (gelesen < 0) break
            if (gelesen > ANTWORT_MAX - antwort.size()) {
                throw BaumFehler("Die Antwort der Gegenstelle ist zu groß.")
            }
            antwort.write(puffer, 0, gelesen)
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

    override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject {
        val adapter = BluetoothAdapter.getDefaultAdapter()
            ?: throw BaumFehler("Dieses Gerät hat kein Bluetooth.")
        if (!adapter.isEnabled) throw BaumFehler("Bluetooth ist ausgeschaltet.")
        val geraet = try {
            adapter.getRemoteDevice(mac)
        } catch (fehler: IllegalArgumentException) {
            throw BaumFehler("Die Bluetooth-Adresse ist ungültig.")
        }
        val offen = try {
            @Suppress("MissingPermission")
            geraet.createRfcommSocketToServiceRecord(DIENST_UUID).also {
                @Suppress("MissingPermission")
                it.connect()
            }
        } catch (fehler: SecurityException) {
            throw BaumFehler("Die Bluetooth-Berechtigung fehlt.")
        } catch (fehler: Exception) {
            throw BaumFehler("Die Bluetooth-Verbindung kam nicht zustande.")
        }
        buchse = offen
        try {
            val hinaus = DataOutputStream(offen.outputStream)
            val herein = DataInputStream(offen.inputStream)
            schreibeRahmen(hinaus, pfad, nutzlast)
            return lieRahmen(herein)
        } finally {
            runCatching { offen.close() }
            buchse = null
        }
    }

    override fun schliessen() {
        runCatching { buchse?.close() }
        buchse = null
    }

    companion object {
        /** Feste Dienstkennung des Magnolienbaums über RFCOMM. */
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
