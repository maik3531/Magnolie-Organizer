package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * Die Nutzlast einer gemeinsamen Notiz, Feld für Feld wie `notizBaumInhalt()`
 * im Organizer.
 *
 * Zwei Felder gehen darüber hinaus: `symbol` und `angelegt`. Der Organizer
 * liest ausschließlich die ihm bekannten Schlüssel und übergeht diese beiden
 * stillschweigend – sie stehen bereit, sobald er sie später auswerten soll.
 */
object Nutzlast {

    /** Größengrenzen des Organizers für Anhänge, damit nichts unzustellbar wird. */
    const val ANHANG_EINZELN_MAX = 12_000_000
    const val ANHANG_GESAMT_MAX = 24_000_000

    private val BILD = Regex("^data:image/(?:jpeg|png|webp|gif);base64,[A-Za-z0-9+/=]+$", RegexOption.IGNORE_CASE)
    private val PDF = Regex("^data:application/pdf;base64,[A-Za-z0-9+/=]+$", RegexOption.IGNORE_CASE)

    fun nutzlastZeichen(dataUrl: String): Int = dataUrl.substringAfter(";base64,", "").length

    fun notizInhalt(notiz: Notiz, art: String, eigeneKennung: String): JsonObject = buildJsonObject {
        put("freigabeId", JsonPrimitive(notiz.baumFreigabe?.id.orEmpty()))
        put("titel", JsonPrimitive(notiz.titel))
        put("text", JsonPrimitive(notiz.text))
        put("html", JsonPrimitive(notiz.html))
        put("anhaenge", anhaengeJson(notiz.anhaenge))
        put("geaendert", JsonPrimitive(if (notiz.baumGeaendert > 0) notiz.baumGeaendert else notiz.geaendert))
        put("version", JsonPrimitive(if (notiz.baumVersion > 0) notiz.baumVersion else 1L))
        put("quelle", JsonPrimitive(notiz.baumQuelle.ifEmpty { eigeneKennung }))
        // Über das Protokoll hinaus, vom Organizer bis auf Weiteres überlesen:
        put("symbol", JsonPrimitive(notiz.symbol))
        put("angelegt", JsonPrimitive(notiz.angelegt))
        put("art", JsonPrimitive(art))
    }

    fun anhaengeJson(anhaenge: List<Anhang>): JsonArray = buildJsonArray {
        var gesamt = 0
        for (anhang in saubere(anhaenge)) {
            if (gesamt + anhang.daten.length > ANHANG_GESAMT_MAX) break
            gesamt += anhang.daten.length
            add(buildJsonObject {
                put("id", JsonPrimitive(anhang.id))
                put("name", JsonPrimitive(anhang.name.take(180)))
                put("art", JsonPrimitive(anhang.art))
                put("daten", JsonPrimitive(anhang.daten))
            })
        }
    }

    /** Dieselbe Prüfung wie `saubereNotizAnhaenge()`: nur Bilder und PDF. */
    fun saubere(anhaenge: List<Anhang>): List<Anhang> {
        val aus = mutableListOf<Anhang>()
        var gesamt = 0
        for (anhang in anhaenge) {
            val daten = anhang.daten.replace(Regex("\\s"), "")
            val istBild = BILD.matches(daten)
            val istPdf = PDF.matches(daten)
            if ((!istBild && !istPdf) || daten.length > ANHANG_EINZELN_MAX ||
                gesamt + daten.length > ANHANG_GESAMT_MAX
            ) continue
            gesamt += daten.length
            aus += anhang.copy(art = if (istPdf) "pdf" else "image", daten = daten)
        }
        return aus
    }

    // ------------------------------------------------------------- Aufgaben

    /**
     * Die Nutzlast einer delegierten Aufgabe, Feld für Feld wie
     * `schickeAnZweig()` im Organizer.
     */
    fun aufgabeInhalt(
        aufgabe: io.gitlab.maik3531.magnolienotes.daten.Aufgabe,
        eigeneKennung: String
    ): JsonObject = buildJsonObject {
        // Der Ursprung behält die Aufgabe; verschickt wird eine Kopie mit
        // genau dieser Kennung, unter der die Rückmeldung später ankommt.
        put("id", JsonPrimitive(aufgabe.fremdId.ifEmpty { aufgabe.id }))
        put("titel", JsonPrimitive(aufgabe.titel))
        put("notiz", JsonPrimitive(aufgabe.notiz))
        put("faellig", JsonPrimitive(aufgabe.faellig))
        put("prio", JsonPrimitive(aufgabe.prio))
        put("erinnern", JsonPrimitive(aufgabe.erinnern))
        put("herkunft", JsonPrimitive(aufgabe.herkunft.ifEmpty { eigeneKennung }))
        put("geaendert", JsonPrimitive(if (aufgabe.geaendert > 0) aufgabe.geaendert else System.currentTimeMillis()))
        put("art", JsonPrimitive("aufgabe"))
    }

    /** Die Rückmeldung erledigt/wieder offen an die Herkunft. */
    fun standInhalt(
        aufgabe: io.gitlab.maik3531.magnolienotes.daten.Aufgabe
    ): JsonObject = buildJsonObject {
        put("id", JsonPrimitive(aufgabe.fremdId))
        put("erledigt", JsonPrimitive(aufgabe.erledigt))
        put("geaendert", JsonPrimitive(if (aufgabe.geaendert > 0) aufgabe.geaendert else System.currentTimeMillis()))
        put("art", JsonPrimitive("stand"))
    }

    /** Was von einer empfangenen Aufgabennachricht gebraucht wird. */
    data class EingegangeneAufgabe(
        val id: String,
        val titel: String,
        val notiz: String,
        val faellig: String,
        val prio: Int,
        val erinnern: Boolean,
        val herkunft: String,
        val geaendert: Long
    )

    /** Der Erledigt-Stand einer Aufgabe, die anderswo abgehakt wurde. */
    data class EingegangenerStand(
        val id: String,
        val erledigt: Boolean,
        val geaendert: Long
    )

    private val ISO_DATUM = Regex("\\d{4}-\\d{2}-\\d{2}")

    fun liesAufgabe(inhalt: JsonObject, vonKennung: String): EingegangeneAufgabe? {
        if (inhalt["art"]?.jsonPrimitive?.contentOrNull != "aufgabe") return null
        val titel = inhalt["titel"]?.jsonPrimitive?.contentOrNull.orEmpty().trim()
        if (titel.isEmpty()) return null
        val prio = inhalt["prio"]?.jsonPrimitive?.contentOrNull?.toIntOrNull() ?: 2
        val faellig = inhalt["faellig"]?.jsonPrimitive?.contentOrNull.orEmpty()
        return EingegangeneAufgabe(
            id = inhalt["id"]?.jsonPrimitive?.contentOrNull.orEmpty(),
            titel = titel,
            notiz = inhalt["notiz"]?.jsonPrimitive?.contentOrNull.orEmpty(),
            faellig = if (ISO_DATUM.matches(faellig)) faellig else "",
            prio = if (prio in 1..3) prio else 2,
            erinnern = inhalt["erinnern"]?.jsonPrimitive?.contentOrNull == "true",
            herkunft = inhalt["herkunft"]?.jsonPrimitive?.contentOrNull.orEmpty()
                .ifEmpty { vonKennung },
            geaendert = inhalt["geaendert"]?.jsonPrimitive?.longOrNull ?: 0L
        )
    }

    fun liesStand(inhalt: JsonObject): EingegangenerStand? {
        if (inhalt["art"]?.jsonPrimitive?.contentOrNull != "stand") return null
        val id = inhalt["id"]?.jsonPrimitive?.contentOrNull.orEmpty()
        if (id.isEmpty()) return null
        return EingegangenerStand(
            id = id,
            erledigt = inhalt["erledigt"]?.jsonPrimitive?.contentOrNull == "true",
            geaendert = inhalt["geaendert"]?.jsonPrimitive?.longOrNull ?: 0L
        )
    }

    // -------------------------------------------------------- Gegenrichtung

    /** Was von einer empfangenen Notiznachricht gebraucht wird. */
    data class Eingegangen(
        val art: String,
        val freigabeId: String,
        val titel: String,
        val text: String,
        val html: String,
        val anhaenge: List<Anhang>,
        val geaendert: Long,
        val version: Long,
        val quelle: String,
        val symbol: String,
        val angelegt: Long
    )

    fun lies(inhalt: JsonObject, vonKennung: String): Eingegangen? {
        val art = inhalt["art"]?.jsonPrimitive?.contentOrNull.orEmpty()
        if (art != "notiz" && art != "notiz_sync") return null
        val freigabeId = inhalt["freigabeId"]?.jsonPrimitive?.contentOrNull.orEmpty()
        if (freigabeId.isEmpty()) return null
        val anhaenge = (inhalt["anhaenge"] as? JsonArray ?: JsonArray(emptyList())).mapNotNull { teil ->
            val objekt = teil as? JsonObject ?: return@mapNotNull null
            Anhang(
                id = objekt["id"]?.jsonPrimitive?.contentOrNull.orEmpty()
                    .ifEmpty { java.util.UUID.randomUUID().toString() },
                name = objekt["name"]?.jsonPrimitive?.contentOrNull.orEmpty(),
                art = objekt["art"]?.jsonPrimitive?.contentOrNull.orEmpty(),
                daten = objekt["daten"]?.jsonPrimitive?.contentOrNull.orEmpty()
            )
        }
        return Eingegangen(
            art = art,
            freigabeId = freigabeId,
            titel = inhalt["titel"]?.jsonPrimitive?.contentOrNull.orEmpty(),
            text = inhalt["text"]?.jsonPrimitive?.contentOrNull.orEmpty(),
            html = inhalt["html"]?.jsonPrimitive?.contentOrNull.orEmpty(),
            anhaenge = saubere(anhaenge),
            geaendert = inhalt["geaendert"]?.jsonPrimitive?.longOrNull ?: 0L,
            version = inhalt["version"]?.jsonPrimitive?.longOrNull ?: 1L,
            quelle = inhalt["quelle"]?.jsonPrimitive?.contentOrNull.orEmpty().ifEmpty { vonKennung },
            symbol = inhalt["symbol"]?.jsonPrimitive?.contentOrNull.orEmpty(),
            angelegt = inhalt["angelegt"]?.jsonPrimitive?.longOrNull ?: 0L
        )
    }

    /**
     * Derselbe schlichte Filter wie `saeubereHtml()` im Organizer: nur
     * Auszeichnungen, keine Attribute außer `href` an `<a>`.
     */
    private val ERLAUBT = setOf("b", "strong", "i", "em", "u", "s", "strike", "del", "br", "div", "p", "span", "a")

    fun saeubereHtml(roh: String): String {
        if (roh.isBlank()) return ""
        val bau = StringBuilder()
        var i = 0
        var gezaehlt = 0
        while (i < roh.length && gezaehlt < 10000) {
            val auf = roh.indexOf('<', i)
            if (auf < 0) {
                bau.append(entschaerfe(roh.substring(i)))
                break
            }
            bau.append(entschaerfe(roh.substring(i, auf)))
            val zu = roh.indexOf('>', auf)
            if (zu < 0) break
            val inhalt = roh.substring(auf + 1, zu).trim()
            val schliessend = inhalt.startsWith("/")
            val name = inhalt.removePrefix("/").takeWhile { !it.isWhitespace() }.lowercase()
            if (name in ERLAUBT) {
                gezaehlt++
                if (name == "a" && !schliessend) {
                    val ziel = Regex("href\\s*=\\s*[\"']([^\"']*)[\"']", RegexOption.IGNORE_CASE)
                        .find(inhalt)?.groupValues?.get(1).orEmpty()
                    if (ziel.startsWith("http://") || ziel.startsWith("https://") ||
                        ziel.startsWith("mailto:")
                    ) {
                        bau.append("<a href=\"").append(entschaerfe(ziel))
                            .append("\" rel=\"noopener noreferrer\">")
                    } else {
                        bau.append("<a>")
                    }
                } else {
                    bau.append(if (schliessend) "</$name>" else "<$name>")
                }
            }
            i = zu + 1
        }
        return bau.toString()
    }

    private fun entschaerfe(text: String): String =
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")

    /** Aus schlichtem Text wird schlichtes HTML – wie `textZuHtml()`. */
    fun textZuHtml(text: String): String =
        text.lineSequence().joinToString("") { "<div>" + entschaerfe(it).ifEmpty { "<br>" } + "</div>" }
}
