package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * Der ältere Umschlag `baum-1` für Zweige, die über den kurzen Codeweg gepaart
 * wurden. Er hat keine Forward Secrecy und keine kryptografische Quittung –
 * `baum-fs1` ist immer vorzuziehen. Er bleibt hier, weil der Organizer ihn für
 * codegepaarte Partner verwendet.
 *
 * Achtung: `umschlag_bauen()` im Organizer schreibt den beglaubigten Zusatz
 * *nicht* kanonisch, sondern mit Pythons Vorgabetrennern. Das wird hier
 * zeichengenau nachgebildet.
 */
object Baum1 {

    /** `json.dumps({"von": …, "zaehler": …}, sort_keys=True)` – mit Leerzeichen. */
    private fun zusatz(von: String, zaehler: Long): ByteArray {
        val bau = StringBuilder("{")
        bau.append(pythonZeichenkette("von")).append(": ").append(pythonZeichenkette(von))
        bau.append(", ")
        bau.append(pythonZeichenkette("zaehler")).append(": ").append(zaehler)
        bau.append("}")
        return bau.toString().toByteArray(Charsets.UTF_8)
    }

    private fun pythonZeichenkette(wert: String): String {
        val bau = StringBuilder("\"")
        for (zeichen in wert) {
            when {
                zeichen == '\\' -> bau.append("\\\\")
                zeichen == '"' -> bau.append("\\\"")
                zeichen.code in 0x20..0x7e -> bau.append(zeichen)
                zeichen == '\u0008' -> bau.append("\\b")
                zeichen == '\u000C' -> bau.append("\\f")
                zeichen == '\n' -> bau.append("\\n")
                zeichen == '\r' -> bau.append("\\r")
                zeichen == '\t' -> bau.append("\\t")
                else -> bau.append("\\u").append("%04x".format(zeichen.code))
            }
        }
        return bau.append('"').toString()
    }

    fun baue(
        eigen: EigeneIdentitaet,
        partnerKennung: String,
        partnerOeffentlich: String,
        inhalt: JsonObject,
        zaehler: Long
    ): JsonObject {
        val schluessel = Krypto.partnerschluessel(
            eigen.geheim, partnerOeffentlich, eigen.kennung, partnerKennung
        )
        val nonce = Krypto.zufallsbytes(12)
        val geheim = Krypto.verschluesseln(
            schluessel, nonce, Kanonisch.bytes(inhalt), zusatz(eigen.kennung, zaehler)
        )
        return buildJsonObject {
            put("magnolie", JsonPrimitive("baum-1"))
            put("von", JsonPrimitive(eigen.kennung))
            put("zaehler", JsonPrimitive(zaehler))
            put("nonce", JsonPrimitive(Krypto.b64(nonce)))
            put("daten", JsonPrimitive(Krypto.b64(geheim)))
        }
    }

    /** Liefert Inhalt und Zähler. Ein schon gesehener Zähler wird abgewiesen. */
    fun oeffne(
        eigen: EigeneIdentitaet,
        partnerKennung: String,
        partnerOeffentlich: String,
        umschlag: JsonObject,
        letzterZaehler: Long
    ): Pair<JsonObject, Long> {
        if (umschlag["magnolie"]?.jsonPrimitive?.contentOrNull != "baum-1") {
            throw BaumFehler("Das ist keine Magnolienbaum-Nachricht.")
        }
        val von = umschlag["von"]?.jsonPrimitive?.contentOrNull.orEmpty()
        if (von != partnerKennung) throw BaumFehler("Die Nachricht kommt von einem anderen Zweig.")
        val zaehler = umschlag["zaehler"]?.jsonPrimitive?.longOrNull
            ?: throw BaumFehler("Die Nachricht ist beschädigt.")
        if (zaehler <= letzterZaehler) throw BaumFehler("Diese Nachricht kam schon einmal an.")
        val schluessel = Krypto.partnerschluessel(
            eigen.geheim, partnerOeffentlich, eigen.kennung, partnerKennung
        )
        val klar = try {
            Krypto.entschluesseln(
                schluessel,
                Krypto.b64Lesen(umschlag["nonce"]?.jsonPrimitive?.contentOrNull, 12),
                Krypto.b64Roh(umschlag["daten"]?.jsonPrimitive?.contentOrNull.orEmpty())
                    ?: throw BaumFehler("Die Nachricht ist beschädigt."),
                zusatz(von, zaehler)
            )
        } catch (fehler: Exception) {
            throw BaumFehler("Die Nachricht ließ sich nicht öffnen.")
        }
        val inhalt = try {
            Kanonisch.json.parseToJsonElement(String(klar, Charsets.UTF_8)).jsonObject
        } catch (fehler: Exception) {
            throw BaumFehler("Der Inhalt ist unlesbar.")
        }
        return inhalt to zaehler
    }
}
