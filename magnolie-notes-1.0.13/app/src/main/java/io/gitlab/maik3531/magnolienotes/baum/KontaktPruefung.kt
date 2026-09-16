package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.KontaktSpur
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

data class KontaktLoeschung(
    val freigabeId: String, val version: Long, val quelle: String, val geaendert: Long
)

object KontaktPruefung {
    fun loeschInhalt(l: KontaktLoeschung): JsonObject = buildJsonObject {
        put("art", JsonPrimitive("kontakt_loeschen")); put("fassung", JsonPrimitive(1))
        put("freigabeId", JsonPrimitive(l.freigabeId)); put("version", JsonPrimitive(l.version))
        put("quelle", JsonPrimitive(l.quelle)); put("geaendert", JsonPrimitive(l.geaendert))
    }

    fun liesLoeschung(o: JsonObject): KontaktLoeschung? {
        if (o.keys != setOf("art", "fassung", "freigabeId", "version", "quelle", "geaendert")) return null
        if (o.text("art") != "kontakt_loeschen" || o.long("fassung") != 1L) return null
        val id = o.text("freigabeId"); val quelle = o.text("quelle")
        val version = o.long("version") ?: return null; val zeit = o.long("geaendert") ?: return null
        if (id.isBlank() || id.length > 128 || quelle.isBlank() || quelle.length > 128 || version <= 0 || zeit < 0) return null
        return KontaktLoeschung(id, version, quelle, zeit)
    }

    /** Ein fehlerhafter, leerer oder stark geschrumpfter Snapshot erzeugt niemals Löschungen. */
    fun fehlendeSpuren(spuren: List<KontaktSpur>, vorhandeneRawIds: Set<Long>, vollstaendig: Boolean): List<KontaktSpur> {
        if (!vollstaendig || vorhandeneRawIds.isEmpty() || spuren.isEmpty()) return emptyList()
        if (vorhandeneRawIds.count { id -> spuren.any { it.rawContactId == id } } * 2 < spuren.size) return emptyList()
        val limit = minOf(10, maxOf(1, spuren.size / 10))
        return spuren.filter { it.rawContactId !in vorhandeneRawIds }.take(limit)
    }

    data class Dublette(val erste: AndroidKontakt, val zweite: AndroidKontakt)

    fun dubletten(kontakte: List<AndroidKontakt>): List<Dublette> {
        val paare = linkedSetOf<Pair<Long, Long>>()
        fun sammeln(schluessel: (AndroidKontakt) -> Set<String>) {
            val index = mutableMapOf<String, MutableList<AndroidKontakt>>()
            kontakte.forEach { k -> schluessel(k).filter(String::isNotBlank).forEach { index.getOrPut(it) { mutableListOf() } += k } }
            index.values.filter { it.size == 2 }.forEach { liste ->
                val ids = liste.map { it.rawContactId }.sorted(); paare += ids[0] to ids[1]
            }
        }
        sammeln { it.daten.telefone.map { w -> telefon(w.wert) }.toSet() }
        sammeln { it.daten.emailEintraege.map { w -> w.wert.trim().lowercase() }.toSet() }
        sammeln { k ->
            val name = listOf(k.daten.vorname, k.daten.nachname, k.daten.firma)
                .joinToString("|") { it.trim().lowercase() }
            if ((k.daten.vorname.isNotBlank() || k.daten.nachname.isNotBlank()) && k.daten.firma.isNotBlank()) setOf(name) else emptySet()
        }
        val nachId = kontakte.associateBy { it.rawContactId }
        return paare.mapNotNull { (a, b) ->
            val erste = nachId[a] ?: return@mapNotNull null; val zweite = nachId[b] ?: return@mapNotNull null
            Dublette(erste, zweite)
        }.take(50)
    }

    fun name(k: KontaktDaten): String = listOf(k.vorname, k.nachname).filter(String::isNotBlank)
        .joinToString(" ").ifBlank { k.anzeigename.ifBlank { k.firma.ifBlank { "?" } } }
    private fun telefon(s: String) = s.filter(Char::isDigit).trimStart('0')
    private fun JsonObject.text(n: String) = this[n]?.jsonPrimitive?.contentOrNull.orEmpty()
    private fun JsonObject.long(n: String) = this[n]?.jsonPrimitive?.longOrNull
}
