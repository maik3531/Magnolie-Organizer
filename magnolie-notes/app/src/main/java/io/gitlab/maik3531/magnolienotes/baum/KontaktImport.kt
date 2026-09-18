package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import java.security.MessageDigest
import java.util.UUID

data class KontaktImportHerkunft(val kontoTyp: String, val kontoName: String, val dataSet: String, val anzahl: Int)
data class KontaktImportVorschau(val id: String, val anzahl: Int, val herkuenfte: List<KontaktImportHerkunft>)

/** Einmaliger read-only Import. Ohne passende Vorschau kann nichts gesendet werden. */
class KontaktImportAblauf(private val senden: (String, JsonObject) -> Unit) {
    private data class Offen(val vorschau: KontaktImportVorschau, val partner: String,
                             val geraet: String, val kontakte: List<AndroidKontakt>, val fassung: Int)
    private var offen: Offen? = null

    fun vorschau(snapshot: KontaktSnapshot, partner: String, geraet: String, fassung: Int = 1): KontaktImportVorschau {
        require(fassung in 1..2)
        require(snapshot.vollstaendig) { "Kontakte konnten nicht vollständig gelesen werden." }
        require(partner.gueltigeKennung() && geraet.gueltigeKennung())
        require(snapshot.kontakte.size <= MAX_KONTAKTE)
        val kontakte = snapshot.kontakte.filter { it.herkuenfte.size <= MAX_KONTAKT_HERKUENFTE }
            .mapNotNull { kontakt -> runCatching { bindung(partner, geraet, kontakt) to kontakt }.getOrNull() }
            .distinctBy { it.first }.map { it.second }
        require(kontakte.isNotEmpty()) { "Kein Kontakt besitzt eine eindeutige stabile Kennung." }
        val gruppen = kontakte.flatMap { kontakt ->
            kontakt.herkuenfte.ifEmpty { listOf(KontaktHerkunft(lookupKey = kontakt.lookupKey)) }
                .map { Triple(it.accountType, it.accountName, it.dataSet) }.distinct()
        }.groupingBy { it }.eachCount()
        require(gruppen.size <= MAX_HERKUENFTE)
        val herkuenfte = gruppen.map { (wert, anzahl) ->
            listOf(wert.first, wert.second, wert.third).forEach { require(it.gueltigerText()) }
            KontaktImportHerkunft(wert.first, wert.second, wert.third, anzahl)
        }.sortedWith(compareBy({ it.kontoName }, { it.kontoTyp }, { it.dataSet }))
        val vorschau = KontaktImportVorschau(UUID.randomUUID().toString(), kontakte.size, herkuenfte)
        val karten = kontakte.map {
            require(KontaktSync.lies(KontaktSync.inhalt(KontaktNachricht("preview", 1, geraet, 0, it.daten, fassung))) != null)
            karte(vorschau.id, partner, geraet, it, fassung)
        }
        require(karten.sumOf { Kanonisch.json.encodeToString(JsonObject.serializer(), it).toByteArray().size } <= MAX_NUTZLAST)
        offen = Offen(vorschau, partner, geraet, kontakte, fassung)
        return vorschau
    }

    fun bestaetigen(vorschauId: String): Int {
        val bereit = offen?.takeIf { it.vorschau.id == vorschauId }
            ?: throw IllegalStateException("Vor dem Senden ist eine aktuelle Vorschau erforderlich.")
        offen = null
        senden("kontakt_import_manifest", manifest(bereit))
        bereit.kontakte.forEach { senden("kontakt_import_karte",
            karte(bereit.vorschau.id, bereit.partner, bereit.geraet, it, bereit.fassung)) }
        return bereit.kontakte.size
    }

    fun abbrechen() { offen = null }

    private fun manifest(offen: Offen) = buildJsonObject {
        put("art", JsonPrimitive("kontakt_import_manifest")); put("fassung", JsonPrimitive(offen.fassung))
        put("importId", JsonPrimitive(offen.vorschau.id)); put("anzahl", JsonPrimitive(offen.vorschau.anzahl))
        put("herkuenfte", buildJsonArray { offen.vorschau.herkuenfte.forEach { h -> add(buildJsonObject {
            put("kontoTyp", JsonPrimitive(h.kontoTyp)); put("kontoName", JsonPrimitive(h.kontoName))
            put("dataSet", JsonPrimitive(h.dataSet)); put("anzahl", JsonPrimitive(h.anzahl))
        }) } })
    }

    private fun karte(importId: String, partner: String, geraet: String, kontakt: AndroidKontakt, fassung: Int): JsonObject {
        val herkuenfte = kontakt.herkuenfte.ifEmpty { listOf(KontaktHerkunft(lookupKey = kontakt.lookupKey)) }
        return buildJsonObject {
            put("art", JsonPrimitive("kontakt_import_karte")); put("fassung", JsonPrimitive(fassung))
            put("importId", JsonPrimitive(importId)); put("bindung", JsonPrimitive(bindung(partner, geraet, kontakt)))
            put("herkuenfte", buildJsonArray { herkuenfte.take(MAX_KONTAKT_HERKUENFTE).forEach { h -> add(buildJsonObject {
                put("kontoTyp", JsonPrimitive(h.accountType)); put("kontoName", JsonPrimitive(h.accountName))
                put("dataSet", JsonPrimitive(h.dataSet))
            }) } })
            put("kontakt", KontaktSync.kontaktJson(kontakt.daten, fassung))
        }
    }

    companion object {
        const val MAX_KONTAKTE = 250
        const val MAX_HERKUENFTE = 64
        const val MAX_KONTAKT_HERKUENFTE = 16
        const val MAX_NUTZLAST = 8 * 1024 * 1024

        fun bindung(partner: String, geraet: String, kontakt: AndroidKontakt): String {
            require(partner.gueltigeKennung() && geraet.gueltigeKennung())
            val quellen = kontakt.herkuenfte.ifEmpty { listOf(KontaktHerkunft(lookupKey = kontakt.lookupKey)) }
                .map { h ->
                    val stabil = h.sourceId.ifBlank { h.lookupKey.ifBlank { kontakt.lookupKey } }
                    require(stabil.isNotBlank()) { "Der Kontakt besitzt weder SOURCE_ID noch Lookup-Schlüssel." }
                    listOf(h.accountType, h.accountName, h.dataSet, stabil).joinToString("\u0000")
                }
                .sorted().joinToString("\u0001")
            val roh = "android-contact-import\u0000$partner\u0000$geraet\u0000$quellen"
            val hash = MessageDigest.getInstance("SHA-256").digest(roh.toByteArray())
                .joinToString("") { "%02x".format(it) }
            return "urn:magnolie:import:android:$hash"
        }

        private fun String.gueltigeKennung() = isNotEmpty() && length <= 128 && none { it.code < 32 }
        private fun String.gueltigerText() = length <= 128 && none { it.code < 32 }
    }
}
