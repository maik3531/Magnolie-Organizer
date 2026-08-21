package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * `baum-fs1` – eine ephemere Sitzung je Nachricht, mit Forward Secrecy.
 * Beide Rollen sind hier abgebildet: die des Absenders (Start bauen, Antwort
 * öffnen, Umschlag senden, Quittung prüfen) und die des Empfängers.
 */
object Sitzung {

    private const val KENN_START = "start\u0000"
    private const val KENN_ANTWORT = "answer\u0000"
    private const val KENN_SCHLUESSEL = "key\u0000"
    private const val KENN_QUITTUNG = "ack\u0000"
    private const val ZUSATZ_DATEN = "magnolienbaum\u0000baum-fs1\u0000data\u0000"

    /** Der Schlüsselplan einer offenen Sitzung. Nach Gebrauch überschrieben. */
    class Offen(
        val sid: String,
        val transkript: ByteArray,
        val kenc: ByteArray,
        val kack: ByteArray
    ) {
        var verbraucht: Boolean = false

        fun loeschen() {
            kenc.fill(0)
            kack.fill(0)
        }
    }

    // ------------------------------------------------------------- Absender

    class Start(val nachricht: JsonObject, val kern: JsonObject, val ephemerGeheim: ByteArray)

    fun baueStart(eigen: EigeneIdentitaet, partnerKennung: String, partnerOeffentlich: String): Start {
        val (geheim, oeffentlich) = Krypto.neuesSchluesselpaar()
        val kern = buildJsonObject {
            put("magnolie", JsonPrimitive("baum-fs1-start"))
            put("von", JsonPrimitive(eigen.kennung))
            put("an", JsonPrimitive(partnerKennung))
            put("sid", JsonPrimitive(Krypto.b64(Krypto.zufallsbytes(16))))
            put("epk", JsonPrimitive(Krypto.b64(oeffentlich)))
        }
        val auth = Krypto.authSchluessel(
            eigen.geheim, partnerOeffentlich, eigen.kennung, partnerKennung
        )
        val nachricht = buildJsonObject {
            kern.forEach { (name, wert) -> put(name, wert) }
            put("mac", JsonPrimitive(Krypto.b64(Krypto.hmacUeber(auth, KENN_START.toByteArray(), kern))))
        }
        return Start(nachricht, kern, geheim)
    }

    fun oeffneAntwort(
        eigen: EigeneIdentitaet,
        partnerKennung: String,
        partnerOeffentlich: String,
        start: Start,
        antwort: JsonObject
    ): Offen {
        val erwartet = setOf("magnolie", "von", "an", "sid", "epk", "startHash", "mac")
        val startHash = Krypto.sha256(Kanonisch.bytes(start.kern))
        if (antwort.keys != erwartet ||
            antwort["magnolie"]?.jsonPrimitive?.contentOrNull != "baum-fs1-antwort" ||
            antwort["von"]?.jsonPrimitive?.contentOrNull != partnerKennung ||
            antwort["an"]?.jsonPrimitive?.contentOrNull != eigen.kennung ||
            antwort["sid"] != start.kern["sid"] ||
            !Krypto.gleich(Krypto.b64Lesen(antwort["startHash"]?.jsonPrimitive?.contentOrNull, 32), startHash)
        ) {
            throw BaumFehler("Die Antwort auf die sichere Sitzung ist ungültig.")
        }
        val antwortKern = buildJsonObject {
            antwort.forEach { (name, wert) -> if (name != "mac") put(name, wert) }
        }
        val auth = Krypto.authSchluessel(
            eigen.geheim, partnerOeffentlich, eigen.kennung, partnerKennung
        )
        val mac = Krypto.b64Lesen(antwort["mac"]?.jsonPrimitive?.contentOrNull, 32)
        if (!Krypto.gleich(mac, Krypto.hmacUeber(auth, KENN_ANTWORT.toByteArray(), antwortKern))) {
            throw BaumFehler("Die Antwort auf die sichere Sitzung ist ungültig.")
        }
        return schluesselplan(
            start.ephemerGeheim,
            Krypto.b64Lesen(antwortKern["epk"]?.jsonPrimitive?.contentOrNull, 32),
            auth, start.kern, antwortKern
        )
    }

    // ------------------------------------------------------------- Empfänger

    class Antwort(val nachricht: JsonObject, val sitzung: Offen)

    fun baueAntwort(
        eigen: EigeneIdentitaet,
        partnerKennung: String,
        partnerOeffentlich: String,
        start: JsonObject
    ): Antwort {
        val erwartet = setOf("magnolie", "von", "an", "sid", "epk", "mac")
        if (start.keys != erwartet ||
            start["magnolie"]?.jsonPrimitive?.contentOrNull != "baum-fs1-start" ||
            start["von"]?.jsonPrimitive?.contentOrNull != partnerKennung ||
            start["an"]?.jsonPrimitive?.contentOrNull != eigen.kennung
        ) {
            throw BaumFehler("Die Anfrage für die sichere Sitzung ist ungültig.")
        }
        Krypto.b64Lesen(start["sid"]?.jsonPrimitive?.contentOrNull, 16)
        val fremdEpk = Krypto.b64Lesen(start["epk"]?.jsonPrimitive?.contentOrNull, 32)
        val startKern = buildJsonObject {
            start.forEach { (name, wert) -> if (name != "mac") put(name, wert) }
        }
        val auth = Krypto.authSchluessel(
            eigen.geheim, partnerOeffentlich, eigen.kennung, partnerKennung
        )
        val mac = Krypto.b64Lesen(start["mac"]?.jsonPrimitive?.contentOrNull, 32)
        if (!Krypto.gleich(mac, Krypto.hmacUeber(auth, KENN_START.toByteArray(), startKern))) {
            throw BaumFehler("Die Anfrage für die sichere Sitzung ist ungültig.")
        }

        val (geheim, oeffentlich) = Krypto.neuesSchluesselpaar()
        val antwortKern = buildJsonObject {
            put("magnolie", JsonPrimitive("baum-fs1-antwort"))
            put("von", JsonPrimitive(eigen.kennung))
            put("an", JsonPrimitive(partnerKennung))
            put("sid", startKern.getValue("sid"))
            put("epk", JsonPrimitive(Krypto.b64(oeffentlich)))
            put("startHash", JsonPrimitive(Krypto.b64(Krypto.sha256(Kanonisch.bytes(startKern)))))
        }
        val nachricht = buildJsonObject {
            antwortKern.forEach { (name, wert) -> put(name, wert) }
            put("mac", JsonPrimitive(Krypto.b64(Krypto.hmacUeber(auth, KENN_ANTWORT.toByteArray(), antwortKern))))
        }
        return Antwort(nachricht, schluesselplan(geheim, fremdEpk, auth, startKern, antwortKern))
    }

    // ------------------------------------------------------------ Umschlag

    fun baueUmschlag(
        sitzung: Offen,
        eigeneKennung: String,
        partnerKennung: String,
        inhalt: JsonObject,
        transportId: String
    ): JsonObject {
        val nonce = Krypto.zufallsbytes(12)
        val kopf = buildJsonObject {
            put("magnolie", JsonPrimitive("baum-fs1"))
            put("von", JsonPrimitive(eigeneKennung))
            put("an", JsonPrimitive(partnerKennung))
            put("sid", JsonPrimitive(sitzung.sid))
            put("mid", JsonPrimitive(transportId))
            put("nonce", JsonPrimitive(Krypto.b64(nonce)))
        }
        val geheim = Krypto.verschluesseln(
            sitzung.kenc, nonce, Kanonisch.bytes(inhalt),
            ZUSATZ_DATEN.toByteArray() + Kanonisch.bytes(kopf)
        )
        return buildJsonObject {
            kopf.forEach { (name, wert) -> put(name, wert) }
            put("daten", JsonPrimitive(Krypto.b64(geheim)))
        }
    }

    /** Liefert Inhalt und Transportkennung. Eine Sitzung öffnet höchstens eine Nachricht. */
    fun oeffneUmschlag(
        sitzung: Offen,
        eigeneKennung: String,
        partnerKennung: String,
        umschlag: JsonObject
    ): Pair<JsonObject, String> {
        if (sitzung.verbraucht) throw BaumFehler("Die sichere Sitzung ist bereits verbraucht.")
        sitzung.verbraucht = true
        val erwartet = setOf("magnolie", "von", "an", "sid", "mid", "nonce", "daten")
        if (umschlag.keys != erwartet ||
            umschlag["magnolie"]?.jsonPrimitive?.contentOrNull != "baum-fs1" ||
            umschlag["von"]?.jsonPrimitive?.contentOrNull != partnerKennung ||
            umschlag["an"]?.jsonPrimitive?.contentOrNull != eigeneKennung ||
            umschlag["sid"]?.jsonPrimitive?.contentOrNull != sitzung.sid
        ) {
            throw BaumFehler("Die sichere Nachricht ist ungültig.")
        }
        val mid = umschlag["mid"]?.jsonPrimitive?.contentOrNull.orEmpty()
        Krypto.b64Lesen(mid, 16)
        val kopf = buildJsonObject {
            umschlag.forEach { (name, wert) -> if (name != "daten") put(name, wert) }
        }
        val nonce = Krypto.b64Lesen(kopf["nonce"]?.jsonPrimitive?.contentOrNull, 12)
        val daten = Krypto.b64Roh(umschlag["daten"]?.jsonPrimitive?.contentOrNull.orEmpty())
            ?: throw BaumFehler("Die sichere Nachricht ist ungültig.")
        if (daten.size < 16) throw BaumFehler("Die sichere Nachricht ist ungültig.")
        val klar = try {
            Krypto.entschluesseln(
                sitzung.kenc, nonce, daten,
                ZUSATZ_DATEN.toByteArray() + Kanonisch.bytes(kopf)
            )
        } catch (fehler: Exception) {
            throw BaumFehler("Die sichere Nachricht ließ sich nicht öffnen.")
        }
        val inhalt = try {
            Kanonisch.json.parseToJsonElement(String(klar, Charsets.UTF_8)).jsonObject
        } catch (fehler: Exception) {
            throw BaumFehler("Der Inhalt ist unlesbar.")
        }
        return inhalt to mid
    }

    fun baueQuittung(sitzung: Offen, umschlag: JsonObject): JsonObject {
        val kern = buildJsonObject {
            put("magnolie", JsonPrimitive("baum-fs1-ack"))
            put("sid", JsonPrimitive(sitzung.sid))
            put("mid", umschlag.getValue("mid"))
        }
        return buildJsonObject {
            kern.forEach { (name, wert) -> put(name, wert) }
            put("mac", JsonPrimitive(Krypto.b64(quittungsMac(sitzung, umschlag, kern))))
        }
    }

    fun pruefeQuittung(sitzung: Offen, umschlag: JsonObject, antwort: JsonObject?): Boolean {
        if (antwort == null) return false
        if (antwort.keys != setOf("magnolie", "sid", "mid", "mac") ||
            antwort["magnolie"]?.jsonPrimitive?.contentOrNull != "baum-fs1-ack" ||
            antwort["sid"]?.jsonPrimitive?.contentOrNull != sitzung.sid ||
            antwort["mid"] != umschlag["mid"]
        ) {
            return false
        }
        val kern = buildJsonObject {
            antwort.forEach { (name, wert) -> if (name != "mac") put(name, wert) }
        }
        val mac = try {
            Krypto.b64Lesen(antwort["mac"]?.jsonPrimitive?.contentOrNull, 32)
        } catch (fehler: BaumFehler) {
            return false
        }
        return Krypto.gleich(mac, quittungsMac(sitzung, umschlag, kern))
    }

    private fun quittungsMac(sitzung: Offen, umschlag: JsonObject, kern: JsonObject): ByteArray {
        val umschlagHash = Krypto.sha256(Kanonisch.bytes(umschlag))
            .joinToString("") { "%02x".format(it) }
        val bindung = buildJsonObject {
            put("transkript", JsonPrimitive(Krypto.b64(sitzung.transkript)))
            put("umschlagHash", JsonPrimitive(umschlagHash))
            put("ack", kern)
        }
        return Krypto.hmacUeber(sitzung.kack, KENN_QUITTUNG.toByteArray(), bindung)
    }

    // ------------------------------------------------------------ Ableitung

    /**
     * Nur für die Drahtprobe: derselbe Schlüsselplan, aber mit vorgegebener
     * ephemerer Hälfte, damit sich die Ableitung des Organizers Byte für Byte
     * nachrechnen lässt.
     */
    internal fun schluesselplanFuerTest(
        ephemerGeheim: ByteArray,
        fremdOeffentlich: ByteArray,
        auth: ByteArray,
        startKern: JsonObject,
        antwortKern: JsonObject
    ): Offen = schluesselplan(ephemerGeheim, fremdOeffentlich, auth, startKern, antwortKern)

    private fun schluesselplan(
        ephemerGeheim: ByteArray,
        fremdOeffentlich: ByteArray,
        auth: ByteArray,
        startKern: JsonObject,
        antwortKern: JsonObject
    ): Offen {
        val gemeinsam = Krypto.austausch(ephemerGeheim, fremdOeffentlich)
        val transkript = Krypto.sha256(
            Kanonisch.bytes(startKern), byteArrayOf(0), Kanonisch.bytes(antwortKern)
        )
        val salzBindung = buildJsonObject {
            put("transkript", JsonPrimitive(Krypto.b64(transkript)))
        }
        val salz = Krypto.hmacUeber(auth, KENN_SCHLUESSEL.toByteArray(), salzBindung)
        val material = Krypto.hkdf(
            gemeinsam, salz,
            Krypto.ZUSATZ + "\u0000baum-fs1\u0000keys\u0000".toByteArray() + transkript,
            64
        )
        val sid = startKern["sid"]?.jsonPrimitive?.contentOrNull.orEmpty()
        return Offen(sid, transkript, material.copyOfRange(0, 32), material.copyOfRange(32, 64))
    }
}
