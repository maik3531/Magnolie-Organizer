package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

/**
 * Der kleine Baumdienst dieses Zweigs: ein HTTP-Server auf Port 8737 mit
 * denselben fünf Wegen wie der Organizer, ein UDP-Rufbeantworter und – über
 * [BluetoothHorcher] – derselbe Satz Wege über RFCOMM.
 *
 * Gehärtet wie das Vorbild: eine Anfrage je Verbindung, feste Längenangabe,
 * `Transfer-Encoding` und `Expect` werden abgewiesen, Bodys sind begrenzt,
 * jede Antwort schließt die Verbindung.
 */
class Server(private val handlung: Handlung, private val wunschPort: Int = Netz.PORT) {

    /** Was der Dienst an die Anwendung zurückmeldet. */
    interface Handlung {
        fun eigen(): EigeneIdentitaet?
        fun istAn(): Boolean
        fun partner(kennung: String): io.gitlab.maik3531.magnolienotes.daten.Partner?
        fun einladungen(): List<Einladung>
        /** Eine erfolgreiche Paarung nach Datei; der Partner gilt als bestätigt. */
        fun paarungFertig(zweig: JsonObject, adresse: String, einladung: Einladung)
        /** Der kurze Codeweg: der Partner wartet auf die Bestätigung des Menschen. */
        fun codeAnfrage(name: String, kennung: String, oeffentlich: String, adresse: String, port: Int)
        /** Eine geöffnete Nachricht eines bestätigten Partners. */
        fun nachricht(vonKennung: String, inhalt: JsonObject)
        fun merkeZaehler(vonKennung: String, zaehler: Long)
        fun schonGesehen(vonKennung: String, transportId: String): Boolean
        fun merkeTransportId(vonKennung: String, transportId: String)
        /** Verarbeitet Inhalt und Replay-Marker in Implementierungen als eine dauerhafte Operation. */
        fun verarbeiteNachricht(
            vonKennung: String,
            inhalt: JsonObject,
            zaehler: Long? = null,
            transportId: String? = null
        ): Boolean {
            if (transportId != null && schonGesehen(vonKennung, transportId)) return false
            nachricht(vonKennung, inhalt)
            if (zaehler != null) merkeZaehler(vonKennung, zaehler)
            if (transportId != null) merkeTransportId(vonKennung, transportId)
            return true
        }
        fun adresseGesehen(vonKennung: String, adresse: String)
    }

    companion object {
        const val PAARUNG_MAX = 128 * 1024
        const val NACHRICHT_MAX = 40 * 1024 * 1024
        const val SITZUNGEN_MAX = 64
        const val SITZUNG_SEKUNDEN = 30L
        const val INAKTIV_MS = 5000
        const val ARBEITER_MAX = 8
        const val WARTESCHLANGE_MAX = 16
        val RUF = "MAGNOLIENBAUM?".toByteArray(Charsets.UTF_8)
    }

    private class OffeneSitzung(
        val sitzung: Sitzung.Offen,
        val partner: String,
        val adresse: String,
        val ablauf: Long
    )

    private class Lauf(val buchse: ServerSocket, val arbeiter: ThreadPoolExecutor) {
        val aktiv = AtomicBoolean(true)
        val rufBuchse = AtomicReference<java.net.DatagramSocket?>()
        val verbindungen = ConcurrentHashMap.newKeySet<Socket>()
    }

    private val sitzungen = ConcurrentHashMap<String, OffeneSitzung>()
    @Volatile private var lauf: Lauf? = null

    val port: Int get() = lauf?.buchse?.localPort ?: wunschPort

    @Synchronized
    fun starten(): Boolean {
        if (lauf != null) return true
        val buchse = try {
            ServerSocket(wunschPort, 16)
        } catch (fehler: Exception) {
            // Ist der Port belegt, nimmt der Dienst den nächsten freien.
            try {
                ServerSocket(0, 16)
            } catch (zweiter: Exception) {
                return false
            }
        }
        val neuerLauf = Lauf(buchse, neuerArbeiter())
        lauf = neuerLauf
        thread(name = "baum-http", isDaemon = true) { horchen(neuerLauf) }
        thread(name = "baum-ruf", isDaemon = true) { rufHorchen(neuerLauf) }
        return true
    }

    @Synchronized
    fun anhalten() {
        val alterLauf = lauf ?: return
        lauf = null
        alterLauf.aktiv.set(false)
        runCatching { alterLauf.buchse.close() }
        runCatching { alterLauf.rufBuchse.getAndSet(null)?.close() }
        alterLauf.verbindungen.forEach { runCatching { it.close() } }
        alterLauf.arbeiter.shutdownNow()
        sitzungen.values.forEach { it.sitzung.loeschen() }
        sitzungen.clear()
    }

    private fun neuerArbeiter() = ThreadPoolExecutor(
        ARBEITER_MAX,
        ARBEITER_MAX,
        0L,
        TimeUnit.MILLISECONDS,
        ArrayBlockingQueue(WARTESCHLANGE_MAX),
        Executors.defaultThreadFactory(),
        ThreadPoolExecutor.AbortPolicy()
    )

    // ------------------------------------------------------------------ HTTP

    private fun horchen(lauf: Lauf) {
        while (lauf.aktiv.get()) {
            val verbindung = try {
                lauf.buchse.accept()
            } catch (fehler: Exception) {
                if (lauf.aktiv.get()) continue else break
            }
            if (!lauf.aktiv.get()) {
                runCatching { verbindung.close() }
                break
            }
            lauf.verbindungen += verbindung
            try {
                verbindung.soTimeout = INAKTIV_MS
                lauf.arbeiter.execute {
                    try {
                        bedienen(verbindung)
                    } finally {
                        lauf.verbindungen.remove(verbindung)
                    }
                }
            } catch (abgewiesen: RejectedExecutionException) {
                lauf.verbindungen.remove(verbindung)
                runCatching { verbindung.close() }
            } catch (fehler: Exception) {
                lauf.verbindungen.remove(verbindung)
                runCatching { verbindung.close() }
            }
        }
    }

    private fun bedienen(verbindung: Socket) {
        try {
            val herein = BufferedInputStream(verbindung.getInputStream())
            val hinaus = verbindung.getOutputStream()
            val kopfzeilen = liesKopf(herein) ?: return antworten(hinaus, 400, fehlerAntwort("Die Anfrage ist unlesbar."))
            val (methode, pfad, kopf) = kopfzeilen
            if (methode != "POST") return antworten(hinaus, 405, fehlerAntwort("Nur POST."))
            if (kopf.containsKey("transfer-encoding")) {
                return antworten(hinaus, 400, fehlerAntwort("Die Anfrage ist unlesbar."))
            }
            if (kopf.containsKey("expect")) {
                return antworten(hinaus, 417, fehlerAntwort("Die Anfrage ist unlesbar."))
            }
            val laengeText = kopf["content-length"]
                ?: return antworten(hinaus, 411, fehlerAntwort("Die Längenangabe fehlt."))
            if (!Regex("(?:0|[1-9][0-9]*)").matches(laengeText)) {
                return antworten(hinaus, 400, fehlerAntwort("Die Anfrage ist unlesbar."))
            }
            val laenge = laengeText.toIntOrNull()
                ?: return antworten(hinaus, 400, fehlerAntwort("Die Anfrage ist unlesbar."))
            val grenze = if (pfad == "/magnolie/v1/nachricht" || pfad == "/magnolie/v2/nachricht") {
                NACHRICHT_MAX
            } else PAARUNG_MAX
            if (laenge > grenze) return antworten(hinaus, 413, fehlerAntwort("Die Nachricht ist zu groß."))

            val roh = ByteArray(laenge)
            var gelesen = 0
            while (gelesen < laenge) {
                val teil = herein.read(roh, gelesen, laenge - gelesen)
                if (teil < 0) return antworten(hinaus, 400, fehlerAntwort("Die Anfrage ist unvollständig."))
                gelesen += teil
            }
            val nachricht = try {
                Kanonisch.json.parseToJsonElement(String(roh, Charsets.UTF_8)).jsonObject
            } catch (fehler: Exception) {
                return antworten(hinaus, 400, fehlerAntwort("Die Anfrage ist unlesbar."))
            }
            val quelle = verbindung.inetAddress?.hostAddress?.substringBefore('%').orEmpty()
            val (nummer, antwort) = behandeln(pfad, nachricht, quelle)
            antworten(hinaus, nummer, antwort)
        } catch (fehler: Exception) {
            // Eine abgebrochene Verbindung ist kein Grund für Aufregung.
        } finally {
            runCatching { verbindung.close() }
        }
    }

    /**
     * Behandelt einen Baumpfad. Wird auch vom Bluetooth-Horcher benutzt –
     * darum kennt diese Stelle kein HTTP.
     */
    fun behandeln(pfad: String, nachricht: JsonObject, quelle: String): Pair<Int, JsonObject> {
        val eigen = handlung.eigen()
        if (eigen == null || !handlung.istAn()) {
            return 503 to fehlerAntwort("Der Magnolienbaum ist ausgeschaltet.")
        }
        return try {
            when (pfad) {
                "/magnolie/v1/paarung" -> 200 to codePaarung(eigen, nachricht, quelle)
                "/magnolie/v2/paarung" -> 200 to dateiPaarung(eigen, nachricht, quelle)
                "/magnolie/v1/nachricht" -> 200 to alteNachricht(eigen, nachricht, quelle)
                "/magnolie/v2/sitzung" -> 200 to sitzungAufbauen(eigen, nachricht, quelle)
                "/magnolie/v2/nachricht" -> 200 to sichereNachricht(eigen, nachricht, quelle)
                else -> 404 to fehlerAntwort("Unbekannter Weg.")
            }
        } catch (abgewiesen: BaumFehler) {
            403 to fehlerAntwort(abgewiesen.message ?: "Abgewiesen.")
        } catch (fehler: Exception) {
            500 to fehlerAntwort("Unerwarteter Fehler.")
        }
    }

    // ---------------------------------------------------------- Baumpfade

    private fun codePaarung(eigen: EigeneIdentitaet, anfrage: JsonObject, quelle: String): JsonObject {
        val name = text(anfrage, "name").take(60)
        val kennung = text(anfrage, "kennung").take(32)
        val oeffentlich = text(anfrage, "oeffentlich")
        if (kennung.isEmpty() || !Paarung.schluesselGueltig(oeffentlich)) {
            throw BaumFehler("Die Paarungsanfrage ist unvollständig.")
        }
        val port = zahl(anfrage, "port")?.toInt() ?: Netz.PORT
        handlung.codeAnfrage(name, kennung, oeffentlich, quelle, port)
        return buildJsonObject {
            put("name", JsonPrimitive(eigen.name))
            put("kennung", JsonPrimitive(eigen.kennung))
            put("oeffentlich", JsonPrimitive(eigen.oeffentlich))
            put("port", JsonPrimitive(eigen.port))
            put("code", JsonPrimitive(Krypto.paarungsCode(eigen.oeffentlich, oeffentlich)))
        }
    }

    private fun dateiPaarung(eigen: EigeneIdentitaet, anfrage: JsonObject, quelle: String): JsonObject {
        val (antwort, zweig, einladung) = Paarung.nimmAnfrageAn(
            eigen, handlung.einladungen(), anfrage
        )
        handlung.paarungFertig(zweig, quelle, einladung)
        return antwort
    }

    private fun alteNachricht(eigen: EigeneIdentitaet, umschlag: JsonObject, quelle: String): JsonObject {
        val von = text(umschlag, "von")
        val partner = handlung.partner(von) ?: throw BaumFehler("Dieser Zweig ist unbekannt.")
        if (!partner.bestaetigt) throw BaumFehler("Dieser Zweig ist noch nicht bestätigt.")
        val (inhalt, zaehler) = Baum1.oeffne(
            eigen, partner.kennung, partner.oeffentlich, umschlag, letzterZaehler(partner)
        )
        handlung.verarbeiteNachricht(von, inhalt, zaehler = zaehler)
        handlung.adresseGesehen(von, quelle)
        return buildJsonObject {
            put("ok", JsonPrimitive(true))
            put("art", inhalt["art"] ?: JsonPrimitive(""))
        }
    }

    private fun sitzungAufbauen(eigen: EigeneIdentitaet, start: JsonObject, quelle: String): JsonObject {
        val von = text(start, "von")
        val partner = handlung.partner(von) ?: throw BaumFehler("Dieser Zweig ist unbekannt.")
        if (!partner.bestaetigt) throw BaumFehler("Dieser Zweig ist noch nicht bestätigt.")
        val jetzt = System.currentTimeMillis() / 1000
        sitzungen.entries.removeIf { eintrag ->
            (eintrag.value.ablauf <= jetzt).also { if (it) eintrag.value.sitzung.loeschen() }
        }
        if (sitzungen.size >= SITZUNGEN_MAX) throw BaumFehler("Zu viele sichere Sitzungen sind offen.")
        val antwort = Sitzung.baueAntwort(eigen, partner.kennung, partner.oeffentlich, start)
        if (sitzungen.containsKey(antwort.sitzung.sid)) {
            antwort.sitzung.loeschen()
            throw BaumFehler("Diese sichere Sitzung gibt es schon.")
        }
        sitzungen[antwort.sitzung.sid] = OffeneSitzung(
            antwort.sitzung, partner.kennung, quelle, jetzt + SITZUNG_SEKUNDEN
        )
        return antwort.nachricht
    }

    private fun sichereNachricht(eigen: EigeneIdentitaet, umschlag: JsonObject, quelle: String): JsonObject {
        val sid = text(umschlag, "sid")
        val offen = sitzungen.remove(sid) ?: throw BaumFehler("Die sichere Sitzung ist unbekannt oder abgelaufen.")
        val jetzt = System.currentTimeMillis() / 1000
        if (offen.ablauf <= jetzt || offen.adresse != quelle) {
            offen.sitzung.loeschen()
            throw BaumFehler("Die sichere Sitzung ist unbekannt oder abgelaufen.")
        }
        try {
            val partner = handlung.partner(offen.partner)
                ?: throw BaumFehler("Dieser Zweig ist unbekannt.")
            if (!partner.bestaetigt) throw BaumFehler("Dieser Zweig ist noch nicht bestätigt.")
            val (inhalt, transportId) = Sitzung.oeffneUmschlag(
                offen.sitzung, eigen.kennung, partner.kennung, umschlag
            )
            handlung.verarbeiteNachricht(partner.kennung, inhalt, transportId = transportId)
            handlung.adresseGesehen(partner.kennung, quelle)
            return Sitzung.baueQuittung(offen.sitzung, umschlag)
        } finally {
            offen.sitzung.loeschen()
        }
    }

    private fun letzterZaehler(partner: io.gitlab.maik3531.magnolienotes.daten.Partner): Long =
        partner.zaehlerRein

    // ------------------------------------------------------------------- UDP

    private fun rufHorchen(lauf: Lauf) {
        if (!lauf.aktiv.get()) return
        val buchse = try {
            java.net.DatagramSocket(null).apply {
                reuseAddress = true
                bind(java.net.InetSocketAddress(lauf.buchse.localPort))
                soTimeout = 500
            }
        } catch (fehler: Exception) {
            return
        }
        if (!lauf.rufBuchse.compareAndSet(null, buchse) || !lauf.aktiv.get()) {
            lauf.rufBuchse.compareAndSet(buchse, null)
            runCatching { buchse.close() }
            return
        }
        val puffer = ByteArray(512)
        while (lauf.aktiv.get()) {
            val paket = java.net.DatagramPacket(puffer, puffer.size)
            try {
                buchse.receive(paket)
            } catch (fehler: java.net.SocketTimeoutException) {
                continue
            } catch (fehler: Exception) {
                break
            }
            val roh = String(paket.data, 0, paket.length, Charsets.UTF_8).trim()
            if (roh != String(RUF, Charsets.UTF_8)) continue
            val eigen = handlung.eigen() ?: continue
            if (!handlung.istAn()) continue
            val antwort = buildJsonObject {
                put("magnolie", JsonPrimitive("baum-1"))
                put("name", JsonPrimitive(eigen.name))
                put("kennung", JsonPrimitive(eigen.kennung))
                put("fingerabdruck", JsonPrimitive(Krypto.fingerabdruck(eigen.oeffentlich)))
                put("port", JsonPrimitive(lauf.buchse.localPort))
            }
            val bytes = Kanonisch.json
                .encodeToString(JsonObject.serializer(), antwort)
                .toByteArray(Charsets.UTF_8)
            runCatching {
                buchse.send(java.net.DatagramPacket(bytes, bytes.size, paket.address, paket.port))
            }
        }
        lauf.rufBuchse.compareAndSet(buchse, null)
        runCatching { buchse.close() }
    }

    /** Ruft ins lokale Netz und sammelt antwortende Zweige ein. */
    fun rufen(wartezeitMs: Int = 1500): List<Gefunden> {
        val gefunden = mutableListOf<Gefunden>()
        val buchse = try {
            java.net.DatagramSocket().apply {
                broadcast = true
                soTimeout = 300
            }
        } catch (fehler: Exception) {
            return gefunden
        }
        try {
            for (ziel in listOf("255.255.255.255", "127.0.0.1")) {
                runCatching {
                    buchse.send(
                        java.net.DatagramPacket(
                            RUF, RUF.size, InetAddress.getByName(ziel), Netz.PORT
                        )
                    )
                }
            }
            val ende = System.currentTimeMillis() + wartezeitMs
            val puffer = ByteArray(1024)
            while (System.currentTimeMillis() < ende) {
                val paket = java.net.DatagramPacket(puffer, puffer.size)
                try {
                    buchse.receive(paket)
                } catch (fehler: Exception) {
                    continue
                }
                runCatching {
                    val antwort = Kanonisch.json.parseToJsonElement(
                        String(paket.data, 0, paket.length, Charsets.UTF_8)
                    ).jsonObject
                    val kennung = text(antwort, "kennung")
                    val eigeneKennung = handlung.eigen()?.kennung
                    if (kennung.isNotEmpty() && kennung != eigeneKennung &&
                        gefunden.none { it.kennung == kennung }
                    ) {
                        gefunden += Gefunden(
                            kennung = kennung,
                            name = text(antwort, "name"),
                            fingerabdruck = text(antwort, "fingerabdruck"),
                            adresse = paket.address.hostAddress?.substringBefore('%').orEmpty(),
                            port = zahl(antwort, "port")?.toInt() ?: Netz.PORT
                        )
                    }
                }
            }
        } finally {
            runCatching { buchse.close() }
        }
        return gefunden
    }

    // ---------------------------------------------------------------- Hilfen

    private fun liesKopf(herein: BufferedInputStream): Triple<String, String, Map<String, String>>? {
        val zeile = liesZeile(herein) ?: return null
        val teile = zeile.split(" ")
        if (teile.size < 2) return null
        val kopf = mutableMapOf<String, String>()
        while (true) {
            val weitere = liesZeile(herein) ?: return null
            if (weitere.isEmpty()) break
            val trenn = weitere.indexOf(':')
            if (trenn <= 0) continue
            kopf[weitere.substring(0, trenn).trim().lowercase()] = weitere.substring(trenn + 1).trim()
            if (kopf.size > 64) return null
        }
        return Triple(teile[0].uppercase(), teile[1], kopf)
    }

    private fun liesZeile(herein: BufferedInputStream): String? {
        val bau = ByteArrayOutputStream()
        while (bau.size() < 8192) {
            val zeichen = herein.read()
            if (zeichen < 0) return if (bau.size() == 0) null else bau.toString("UTF-8")
            if (zeichen == '\n'.code) return bau.toString("UTF-8").trimEnd('\r')
            bau.write(zeichen)
        }
        return null
    }

    private fun antworten(hinaus: OutputStream, nummer: Int, inhalt: JsonObject) {
        val roh = Kanonisch.json
            .encodeToString(JsonObject.serializer(), inhalt)
            .toByteArray(Charsets.UTF_8)
        val kopf = buildString {
            append("HTTP/1.1 ").append(nummer).append(' ').append(grundtext(nummer)).append("\r\n")
            append("Content-Type: application/json\r\n")
            append("Content-Length: ").append(roh.size).append("\r\n")
            append("Connection: close\r\n\r\n")
        }
        hinaus.write(kopf.toByteArray(Charsets.US_ASCII))
        hinaus.write(roh)
        hinaus.flush()
    }

    private fun grundtext(nummer: Int) = when (nummer) {
        200 -> "OK"
        400 -> "Bad Request"
        403 -> "Forbidden"
        404 -> "Not Found"
        405 -> "Method Not Allowed"
        411 -> "Length Required"
        413 -> "Payload Too Large"
        417 -> "Expectation Failed"
        429 -> "Too Many Requests"
        503 -> "Service Unavailable"
        else -> "Error"
    }

    private fun fehlerAntwort(text: String): JsonObject =
        buildJsonObject { put("fehler", JsonPrimitive(text)) }
}

/** Ein im lokalen Netz gefundener Zweig. */
data class Gefunden(
    val kennung: String,
    val name: String,
    val fingerabdruck: String,
    val adresse: String,
    val port: Int
)

internal fun text(objekt: JsonObject, name: String): String =
    (objekt[name] as? JsonPrimitive)?.content.orEmpty()

internal fun zahl(objekt: JsonObject, name: String): Long? =
    (objekt[name] as? JsonPrimitive)?.content?.toLongOrNull()
