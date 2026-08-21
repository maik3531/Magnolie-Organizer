package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.longOrNull

/**
 * Die Paarungsdatei in Fassung 2 – Prüfung, Anfrage, Antwortprüfung.
 * Vorlage sind `baum_paarungsdatei_pruefen()`, `baum_paarungsanfrage_bauen()`
 * und `baum_paarungsantwort_pruefen()` im Organizer.
 */
object Paarung {

    const val DATEI_MAX = 8192
    private val FELDER = setOf(
        "magnolie", "fassung", "paarung", "erstellt", "gueltigBis",
        "ziel", "einlader", "geheimnis", "mac"
    )
    private val OEFFENTLICHE_FELDER = listOf(
        "magnolie", "fassung", "paarung", "erstellt", "gueltigBis", "ziel", "einlader"
    )

    /** Liest die Datei und prüft Bindung, Ablauf und Ziel. */
    fun pruefeDatei(text: String, jetztSekunden: Long = System.currentTimeMillis() / 1000): JsonObject {
        if (text.toByteArray(Charsets.UTF_8).size > DATEI_MAX) {
            throw BaumFehler("Die Paarungsdatei ist zu groß.")
        }
        val dokument = try {
            Kanonisch.json.parseToJsonElement(text).jsonObject
        } catch (fehler: Exception) {
            throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        }
        return pruefe(dokument, jetztSekunden)
    }

    fun pruefe(dokument: JsonObject, jetztSekunden: Long): JsonObject {
        val erstellt = dokument["erstellt"]?.jsonPrimitive?.longOrNull
        val gueltigBis = dokument["gueltigBis"]?.jsonPrimitive?.longOrNull
        if (dokument.keys != FELDER ||
            dokument["magnolie"]?.jsonPrimitive?.contentOrNull != "magnolie-paarungsdatei" ||
            dokument["fassung"]?.jsonPrimitive?.intOrNull != 2 ||
            erstellt == null || gueltigBis == null
        ) {
            throw BaumFehler("Die Paarungsdatei ist ungültig.")
        }
        if (gueltigBis <= jetztSekunden) {
            throw BaumFehler("Die Paarungsdatei ist abgelaufen. Erzeuge im Organizer eine neue.")
        }
        if (gueltigBis - erstellt > 3600) {
            throw BaumFehler("Die Paarungsdatei behauptet eine zu lange Gültigkeit.")
        }
        val ziel = dokument["ziel"]?.jsonObject ?: throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        val einlader = dokument["einlader"]?.jsonObject
            ?: throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        if (ziel.keys != setOf("adresse", "port") ||
            einlader.keys != setOf("kennung", "name", "oeffentlich", "port")
        ) {
            throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        }
        val port = ziel["port"]?.jsonPrimitive?.intOrNull ?: 0
        if (port !in 1..65535) throw BaumFehler("Der Port in der Paarungsdatei ist ungültig.")
        val kennung = einlader["kennung"]?.jsonPrimitive?.contentOrNull.orEmpty()
        val oeffentlich = einlader["oeffentlich"]?.jsonPrimitive?.contentOrNull.orEmpty()
        if (kennung.isEmpty() || !schluesselGueltig(oeffentlich)) {
            throw BaumFehler("Die Paarungsdatei ist beschädigt.")
        }

        val geheimnis = Krypto.b64UrlLesen(dokument["geheimnis"]?.jsonPrimitive?.contentOrNull, 32)
        val commitment = Krypto.b64UrlLesen(dokument["paarung"]?.jsonPrimitive?.contentOrNull, 32)
        val erwartet = Krypto.sha256("magnolie-pair-commit-v2\u0000".toByteArray(), geheimnis)
        val mac = Krypto.b64UrlLesen(dokument["mac"]?.jsonPrimitive?.contentOrNull, 32)
        val erwarteterMac = Krypto.hmacUeber(
            geheimnis, "magnolie-pair-file-v2\u0000".toByteArray(), oeffentlicheFelder(dokument)
        )
        if (!Krypto.gleich(commitment, erwartet) || !Krypto.gleich(mac, erwarteterMac)) {
            throw BaumFehler("Die Paarungsdatei wurde verändert.")
        }
        return dokument
    }

    private fun oeffentlicheFelder(dokument: JsonObject): JsonObject = buildJsonObject {
        for (name in OEFFENTLICHE_FELDER) put(name, dokument.getValue(name))
    }

    /** Baut die Anfrage an `POST /magnolie/v2/paarung`. Das Geheimnis bleibt hier. */
    fun anfrage(dokument: JsonObject, eigen: EigeneIdentitaet): JsonObject {
        val geheimnis = Krypto.b64UrlLesen(dokument["geheimnis"]?.jsonPrimitive?.contentOrNull, 32)
        val kern = buildJsonObject {
            put("magnolie", JsonPrimitive("baum-paarung-2"))
            put("paarung", dokument.getValue("paarung"))
            put("nonce", JsonPrimitive(Krypto.b64Url(Krypto.zufallsbytes(32))))
            put("zweig", eigen.alsZweig())
        }
        val beweis = Krypto.hmacUeber(
            geheimnis, "magnolie-pair-request-v2\u0000".toByteArray(), kern
        )
        return buildJsonObject {
            kern.forEach { (name, wert) -> put(name, wert) }
            put("beweis", JsonPrimitive(Krypto.b64Url(beweis)))
        }
    }

    /** Prüft, dass die Gegenstelle das Dateigeheimnis wirklich besitzt. */
    fun pruefeAntwort(dokument: JsonObject, anfrage: JsonObject, antwort: JsonObject) {
        val geheimnis = Krypto.b64UrlLesen(dokument["geheimnis"]?.jsonPrimitive?.contentOrNull, 32)
        val erwarteteFelder = setOf("magnolie", "paarung", "nonce", "zweig", "beweis")
        if (antwort.keys != erwarteteFelder ||
            antwort["magnolie"]?.jsonPrimitive?.contentOrNull != "baum-paarung-2-antwort" ||
            antwort["paarung"] != dokument["paarung"] ||
            antwort["nonce"] != anfrage["nonce"] ||
            antwort["zweig"] != dokument["einlader"]
        ) {
            throw BaumFehler("Der andere Zweig hat die Paarungsdatei nicht nachgewiesen.")
        }
        val kern = buildJsonObject {
            antwort.forEach { (name, wert) -> if (name != "beweis") put(name, wert) }
        }
        val beweis = Krypto.b64UrlLesen(antwort["beweis"]?.jsonPrimitive?.contentOrNull, 32)
        val erwartet = Krypto.hmacUeber(
            geheimnis, "magnolie-pair-response-v2\u0000".toByteArray(), kern
        )
        if (!Krypto.gleich(beweis, erwartet)) {
            throw BaumFehler("Der andere Zweig hat die Paarungsdatei nicht nachgewiesen.")
        }
    }

    // ------------------------------------------------- Rolle des Einladers

    /**
     * Erzeugt eine Paarungsdatei, die am Rechner in den Organizer eingelesen
     * werden kann. `adresse` ist die WLAN-Adresse dieses Handys.
     */
    fun erzeugeDatei(
        eigen: EigeneIdentitaet,
        adresse: String,
        jetztSekunden: Long = System.currentTimeMillis() / 1000
    ): Pair<JsonObject, Einladung> {
        val geheimnis = Krypto.zufallsbytes(32)
        val commitment = Krypto.sha256("magnolie-pair-commit-v2\u0000".toByteArray(), geheimnis)
        val gueltigBis = jetztSekunden + 15 * 60
        val kern = buildJsonObject {
            put("magnolie", JsonPrimitive("magnolie-paarungsdatei"))
            put("fassung", JsonPrimitive(2))
            put("paarung", JsonPrimitive(Krypto.b64Url(commitment)))
            put("erstellt", JsonPrimitive(jetztSekunden))
            put("gueltigBis", JsonPrimitive(gueltigBis))
            put("ziel", buildJsonObject {
                put("adresse", JsonPrimitive(adresse))
                put("port", JsonPrimitive(eigen.port))
            })
            put("einlader", eigen.alsZweig())
        }
        val mac = Krypto.hmacUeber(geheimnis, "magnolie-pair-file-v2\u0000".toByteArray(), kern)
        val dokument = buildJsonObject {
            kern.forEach { (name, wert) -> put(name, wert) }
            put("geheimnis", JsonPrimitive(Krypto.b64Url(geheimnis)))
            put("mac", JsonPrimitive(Krypto.b64Url(mac)))
        }
        return dokument to Einladung(
            paarung = Krypto.b64Url(commitment),
            geheimnis = Krypto.b64Url(geheimnis),
            gueltigBis = gueltigBis
        )
    }

    /**
     * Nimmt eine `baum-paarung-2`-Anfrage an; Vorlage ist
     * `baum_paarungsanfrage_annehmen()`. Liefert Antwort und den neuen Partner.
     */
    fun nimmAnfrageAn(
        eigen: EigeneIdentitaet,
        einladungen: List<Einladung>,
        anfrage: JsonObject,
        jetztSekunden: Long = System.currentTimeMillis() / 1000
    ): Triple<JsonObject, JsonObject, Einladung> {
        if (anfrage.keys != setOf("magnolie", "paarung", "nonce", "zweig", "beweis") ||
            anfrage["magnolie"]?.jsonPrimitive?.contentOrNull != "baum-paarung-2"
        ) {
            throw BaumFehler("Die Paarungsanfrage ist ungültig.")
        }
        val kennungDerPaarung = anfrage["paarung"]?.jsonPrimitive?.contentOrNull
        val einladung = einladungen.firstOrNull {
            it.paarung == kennungDerPaarung && it.gueltigBis > jetztSekunden
        } ?: throw BaumFehler("Die Paarungsdatei gilt nicht mehr.")

        val geheimnis = Krypto.b64UrlLesen(einladung.geheimnis, 32)
        Krypto.b64UrlLesen(anfrage["nonce"]?.jsonPrimitive?.contentOrNull, 32)
        val zweig = anfrage["zweig"]?.jsonObject ?: throw BaumFehler("Die Paarungsanfrage ist ungültig.")
        if (zweig.keys != setOf("kennung", "name", "oeffentlich", "port") ||
            zweig["kennung"]?.jsonPrimitive?.contentOrNull.isNullOrEmpty() ||
            !schluesselGueltig(zweig["oeffentlich"]?.jsonPrimitive?.contentOrNull.orEmpty())
        ) {
            throw BaumFehler("Die Paarungsanfrage ist ungültig.")
        }
        val kern = buildJsonObject {
            anfrage.forEach { (name, wert) -> if (name != "beweis") put(name, wert) }
        }
        val beweis = Krypto.b64UrlLesen(anfrage["beweis"]?.jsonPrimitive?.contentOrNull, 32)
        val erwartet = Krypto.hmacUeber(
            geheimnis, "magnolie-pair-request-v2\u0000".toByteArray(), kern
        )
        if (!Krypto.gleich(beweis, erwartet)) {
            throw BaumFehler("Die Paarungsanfrage ist ungültig.")
        }

        val antwortKern = buildJsonObject {
            put("magnolie", JsonPrimitive("baum-paarung-2-antwort"))
            put("paarung", anfrage.getValue("paarung"))
            put("nonce", anfrage.getValue("nonce"))
            put("zweig", eigen.alsZweig())
        }
        val antwortBeweis = Krypto.hmacUeber(
            geheimnis, "magnolie-pair-response-v2\u0000".toByteArray(), antwortKern
        )
        val antwort = buildJsonObject {
            antwortKern.forEach { (name, wert) -> put(name, wert) }
            put("beweis", JsonPrimitive(Krypto.b64Url(antwortBeweis)))
        }
        return Triple(antwort, zweig, einladung)
    }

    fun schluesselGueltig(oeffentlichB64: String): Boolean =
        Krypto.b64Roh(oeffentlichB64)?.size == 32
}

/** Eine offene Einladung – das Einmalgeheimnis liegt nur hier. */
@kotlinx.serialization.Serializable
data class Einladung(
    val paarung: String,
    val geheimnis: String,
    val gueltigBis: Long
)

/** Die eigenen öffentlichen Identitätsfelder, wie sie über das Netz gehen. */
data class EigeneIdentitaet(
    val kennung: String,
    val name: String,
    val oeffentlich: String,
    val geheim: String,
    val port: Int
) {
    fun alsZweig(): JsonObject = buildJsonObject {
        put("kennung", JsonPrimitive(kennung))
        put("name", JsonPrimitive(name))
        put("oeffentlich", JsonPrimitive(oeffentlich))
        put("port", JsonPrimitive(port))
    }
}
