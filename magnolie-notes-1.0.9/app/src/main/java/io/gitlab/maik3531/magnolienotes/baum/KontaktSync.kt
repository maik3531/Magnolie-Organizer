package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.Serializable
import java.security.MessageDigest
import java.time.LocalDate
import java.util.Base64

@Serializable
data class KontaktWert(val art: String = "", val wert: String = "")
@Serializable
data class KontaktAnschrift(
    val art: String = "", val strasse: String = "", val plz: String = "",
    val ort: String = "", val region: String = "", val land: String = ""
)
@Serializable
data class KontaktDaten(
    val vorname: String = "", val nachname: String = "", val firma: String = "",
    val notiz: String = "", val geburtstag: String = "", val foto: String = "",
    val telefone: List<KontaktWert> = emptyList(),
    val emailEintraege: List<KontaktWert> = emptyList(),
    val anschriften: List<KontaktAnschrift> = emptyList()
)
@Serializable
data class KontaktNachricht(
    val freigabeId: String, val version: Long, val quelle: String,
    val geaendert: Long, val kontakt: KontaktDaten
)

/** Interoperabler Vertrag und reine, auf der JVM testbare Kontaktlogik. */
object KontaktSync {
    private const val TEXT_MAX = 2_048
    private const val NOTIZ_MAX = 20_000
    private const val LISTE_MAX = 100
    const val FOTO_TEXT_MAX = 2_800_000
    private val VOLLES_DATUM = Regex("\\d{4}-\\d{2}-\\d{2}")
    private val JAHRLOSES_DATUM = Regex("--(\\d{2})-(\\d{2})")
    private val FOTO = Regex("^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/]*={0,2})$")
    private val LOESCHMARKER = setOf(
        "delete", "deleted", "deletion", "tombstone", "loeschen", "löschen", "geloescht", "gelöscht")

    fun inhalt(n: KontaktNachricht): JsonObject = buildJsonObject {
        put("art", JsonPrimitive("kontakt_sync"))
        put("fassung", JsonPrimitive(1))
        put("freigabeId", JsonPrimitive(n.freigabeId))
        put("version", JsonPrimitive(n.version))
        put("quelle", JsonPrimitive(n.quelle))
        put("geaendert", JsonPrimitive(n.geaendert))
        put("kontakt", kontaktJson(n.kontakt))
    }

    private fun kontaktJson(k: KontaktDaten) = buildJsonObject {
        put("vorname", JsonPrimitive(k.vorname)); put("nachname", JsonPrimitive(k.nachname))
        put("firma", JsonPrimitive(k.firma)); put("notiz", JsonPrimitive(k.notiz))
        put("geburtstag", JsonPrimitive(k.geburtstag))
        if (k.foto.isNotEmpty()) put("foto", JsonPrimitive(k.foto))
        put("telefone", werteJson(k.telefone)); put("emailEintraege", werteJson(k.emailEintraege))
        put("anschriften", buildJsonArray { k.anschriften.forEach { a -> add(buildJsonObject {
            put("art", JsonPrimitive(a.art)); put("strasse", JsonPrimitive(a.strasse))
            put("plz", JsonPrimitive(a.plz)); put("ort", JsonPrimitive(a.ort))
            put("region", JsonPrimitive(a.region)); put("land", JsonPrimitive(a.land))
        }) } })
    }

    private fun werteJson(werte: List<KontaktWert>) = buildJsonArray { werte.forEach { w ->
        add(buildJsonObject { put("art", JsonPrimitive(w.art)); put("wert", JsonPrimitive(w.wert)) })
    } }

    fun lies(o: JsonObject): KontaktNachricht? = runCatching {
        if (o.text("art") != "kontakt_sync" || o.long("fassung") != 1L) return null
        if (o.keys != setOf("art", "fassung", "freigabeId", "version", "quelle", "geaendert", "kontakt")) return null
        val id = o.text("freigabeId"); val quelle = o.text("quelle")
        val version = o.long("version") ?: return null
        val geaendert = o.long("geaendert") ?: return null
        if (id.isEmpty() || id.codePointAnzahl() > 128 || id.hatC0() ||
            quelle.isEmpty() || quelle.codePointAnzahl() > 128 || quelle.hatC0() ||
            version <= 0 || geaendert < 0) return null
        val k = o["kontakt"] as? JsonObject ?: return null
        val pflicht = setOf("vorname", "nachname", "firma", "notiz", "geburtstag",
            "telefone", "emailEintraege", "anschriften")
        if (k.keys != pflicht && k.keys != pflicht + "foto") return null
        val geburtstag = k.text("geburtstag")
        val foto = k.text("foto")
        if (foto.isNotEmpty() && fotoBytes(foto) == null) return null
        val daten = KontaktDaten(
            vorname = k.kurzer("vorname") ?: return null,
            nachname = k.kurzer("nachname") ?: return null,
            firma = k.kurzer("firma") ?: return null,
            notiz = k.text("notiz").takeIf { it.codePointAnzahl() <= NOTIZ_MAX } ?: return null,
            geburtstag = geburtstag.takeIf { it.isEmpty() || datumGueltig(it) } ?: return null,
            foto = foto,
            telefone = liesWerte(k["telefone"] as? JsonArray ?: return null) ?: return null,
            emailEintraege = liesWerte(k["emailEintraege"] as? JsonArray ?: return null) ?: return null,
            anschriften = liesAnschriften(k["anschriften"] as? JsonArray ?: return null) ?: return null
        )
        KontaktNachricht(id, version, quelle, geaendert, normalisiere(daten))
    }.getOrNull()

    private fun liesWerte(a: JsonArray): List<KontaktWert>? {
        if (a.size > LISTE_MAX) return null
        return a.map { e ->
            val o = e as? JsonObject ?: return null
            if (o.keys != setOf("art", "wert")) return null
            KontaktWert(o.listenText("art", true) ?: return null,
                o.listenText("wert") ?: return null)
        }
    }

    private fun liesAnschriften(a: JsonArray): List<KontaktAnschrift>? {
        if (a.size > LISTE_MAX) return null
        val felder = setOf("art", "strasse", "plz", "ort", "region", "land")
        return a.map { e ->
            val o = e as? JsonObject ?: return null
            if (o.keys != felder) return null
            KontaktAnschrift(o.listenText("art", true) ?: return null,
                o.listenText("strasse") ?: return null, o.listenText("plz") ?: return null,
                o.listenText("ort") ?: return null, o.listenText("region") ?: return null,
                o.listenText("land") ?: return null)
        }
    }

    /** Leere Gegenwerte löschen nichts; Mehrfachfelder werden normalisiert addiert. */
    fun mische(lokal: KontaktDaten, fern: KontaktDaten): KontaktDaten = KontaktDaten(
        vorname = fern.vorname.ifBlank { lokal.vorname },
        nachname = fern.nachname.ifBlank { lokal.nachname },
        firma = fern.firma.ifBlank { lokal.firma }, notiz = fern.notiz.ifBlank { lokal.notiz },
        geburtstag = fern.geburtstag.ifBlank { lokal.geburtstag },
        foto = lokal.foto.ifBlank { fern.foto },
        telefone = vereinige(lokal.telefone, fern.telefone) { normalWert(it.wert) },
        emailEintraege = vereinige(lokal.emailEintraege, fern.emailEintraege) { it.wert.trim().lowercase() },
        anschriften = vereinige(lokal.anschriften, fern.anschriften) { anschriftSchluessel(it) }
    )

    fun normalisiere(k: KontaktDaten) = k.copy(
        telefone = vereinige(emptyList(), k.telefone.filter { it.wert.isNotBlank() }) { normalWert(it.wert) },
        emailEintraege = vereinige(emptyList(), k.emailEintraege.filter { it.wert.isNotBlank() }) { it.wert.trim().lowercase() },
        anschriften = vereinige(emptyList(), k.anschriften.filter { anschriftSchluessel(it).isNotBlank() }) { anschriftSchluessel(it) }
    )

    private fun <T> vereinige(a: List<T>, b: List<T>, schluessel: (T) -> String): List<T> =
        (a + b).distinctBy(schluessel)
    private fun normalWert(s: String) = s.filter { it.isDigit() || it == '+' }.trimStart('+')
    private fun anschriftSchluessel(a: KontaktAnschrift) =
        listOf(a.strasse, a.plz, a.ort, a.region, a.land).joinToString("|") { it.trim().lowercase() }

    fun fotoDataUrl(bytes: ByteArray): String {
        if (bytes.isEmpty()) return ""
        val mime = bildMime(bytes) ?: return ""
        val aus = "data:$mime;base64," + Base64.getEncoder().encodeToString(bytes)
        return aus.takeIf { it.length <= FOTO_TEXT_MAX } ?: ""
    }

    fun fotoBytes(foto: String): ByteArray? {
        if (foto.isEmpty()) return ByteArray(0)
        if (foto.length > FOTO_TEXT_MAX || foto.any(Char::isWhitespace)) return null
        val match = FOTO.matchEntire(foto) ?: return null
        val bytes = runCatching { Base64.getDecoder().decode(match.groupValues[2]) }.getOrNull() ?: return null
        return bytes.takeIf { it.isNotEmpty() &&
            Base64.getEncoder().encodeToString(it) == match.groupValues[2] }
    }

    private fun bildMime(b: ByteArray): String? = when {
        b.size >= 3 && b[0] == 0xff.toByte() && b[1] == 0xd8.toByte() && b[2] == 0xff.toByte() -> "image/jpeg"
        b.size >= 8 && b.sliceArray(0..7).contentEquals(byteArrayOf(
            0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) -> "image/png"
        b.size >= 12 && String(b, 0, 4, Charsets.US_ASCII) == "RIFF" &&
            String(b, 8, 4, Charsets.US_ASCII) == "WEBP" -> "image/webp"
        else -> null
    }

    fun hash(k: KontaktDaten): String {
        val roh = Kanonisch.json.encodeToString(JsonObject.serializer(), kontaktJson(normalisiere(k)))
        return MessageDigest.getInstance("SHA-256").digest(roh.toByteArray())
            .joinToString("") { "%02x".format(it) }
    }

    fun istNeu(n: KontaktNachricht, version: Long, quelle: String): Boolean =
        n.version > version || (n.version == version && n.quelle > quelle)

    private fun JsonObject.text(name: String) = this[name]?.jsonPrimitive?.contentOrNull.orEmpty()
    private fun JsonObject.long(name: String) = this[name]?.jsonPrimitive?.longOrNull
    private fun JsonObject.kurzer(name: String) = text(name).takeIf { it.codePointAnzahl() <= TEXT_MAX }
    private fun JsonObject.listenText(name: String, art: Boolean = false): String? = text(name).takeIf {
        it.codePointAnzahl() <= TEXT_MAX && !it.startsWith("data:", ignoreCase = true) &&
            (!art || it.trim().lowercase() !in LOESCHMARKER)
    }
    private fun String.codePointAnzahl() = codePointCount(0, length)
    private fun String.hatC0() = codePoints().anyMatch { it < 32 }
    private fun datumGueltig(value: String): Boolean {
        if (VOLLES_DATUM.matches(value)) return value.take(4) != "0000" && runCatching { LocalDate.parse(value) }.isSuccess
        val match = JAHRLOSES_DATUM.matchEntire(value) ?: return false
        val monat = match.groupValues[1].toInt()
        val tag = match.groupValues[2].toInt()
        val maximum = when (monat) { 2 -> 29; 4, 6, 9, 11 -> 30; in 1..12 -> 31; else -> return false }
        return tag in 1..maximum
    }
}
