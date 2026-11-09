package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import java.util.IdentityHashMap
import java.util.UUID
import org.threeten.bp.Instant
import org.threeten.bp.temporal.ChronoUnit

internal class BookRestoreException(val code: String) : Exception(code)

/** Pure whole-book transform; neither a durable receipt nor remote-sync authority. */
internal object BookRestore {
    const val MAXIMUM_BYTES = MAX_BYTES / 2 // Existing Vault data limit, not the larger envelope cap.
    const val MAXIMUM_QUARANTINE_ENTRIES = 100_000
    private val domains = listOf("aufgaben", "kontakte", "termine")
    private fun fail(code: String = "invalid_input"): Nothing = throw BookRestoreException(code)
    internal fun objectAt(parent: JSONObject, key: String): JSONObject =
        if (!parent.has(key)) JSONObject() else parent.opt(key) as? JSONObject ?: fail()
    private fun rows(parent: JSONObject, key: String): JSONArray =
        if (!parent.has(key)) JSONArray() else parent.opt(key) as? JSONArray ?: fail("unsupported_quarantine")
    internal fun uuid(value: Any?): UUID? {
        if (value !is String || !value.matches(Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"))) return null
        return try { UUID.fromString(value) } catch (_: IllegalArgumentException) { null }
    }
    fun persistedEpoch(book: JSONObject): UUID {
        val meta = objectAt(book,"syncMetadaten"); val sync = objectAt(objectAt(book,"einstellungen"),"sync")
        val epoch = uuid(book.opt("syncEpoch")) ?: fail("invalid_epoch")
        if (uuid(meta.opt("syncEpoch")) != epoch || sync.has("syncEpoch") && uuid(sync.opt("syncEpoch")) != epoch) fail("invalid_epoch")
        return epoch
    }
    /** Aggregate bound BEFORE cloning/stringifying, including caller-built objects and cycles. */
    internal fun preflight(value: Any, maximumBytes: Int = MAXIMUM_BYTES): Int {
        if (maximumBytes !in 1..MAXIMUM_BYTES) fail("limit")
        var remaining = maximumBytes; var nodes = 0
        val ancestors = IdentityHashMap<Any, Boolean>()
        fun reserve(count: Int) { if (count < 0 || count > remaining) fail("limit"); remaining -= count }
        fun walk(item: Any?, depth: Int) {
            if (depth >= 64 || ++nodes > 2_000_000) fail("limit")
            when (item) {
                null, JSONObject.NULL -> reserve(4)
                is String -> {
                    reserve(2); var index = 0
                    while (index < item.length) {
                        val c = item[index++].code
                        when {
                            c < 32 || c == 0x2028 || c == 0x2029 -> reserve(6)
                            c == 34 || c == 92 || c == 47 -> reserve(2)
                            c < 128 -> reserve(1)
                            c < 2048 -> reserve(2)
                            c in 0xd800..0xdbff -> { if (index == item.length || item[index].code !in 0xdc00..0xdfff) fail(); index++; reserve(4) }
                            c in 0xdc00..0xdfff -> fail()
                            else -> reserve(3)
                        }
                    }
                }
                is Boolean -> reserve(5)
                is Number -> {
                    if (item !is Byte && item !is Short && item !is Int && item !is Long && item !is Float && item !is Double &&
                        item !is java.math.BigInteger && item !is java.math.BigDecimal) fail()
                    if (!item.toDouble().isFinite()) fail()
                    reserve(maxOf(32,item.toString().length))
                }
                is JSONObject, is JSONArray -> {
                    if (ancestors.put(item, true) != null) fail()
                    reserve(2)
                    if (item is JSONObject) for (key in item.keys().asSequence()) { walk(key,depth+1); reserve(2); walk(item.get(key),depth+1) }
                    else { item as JSONArray; for (i in 0 until item.length()) { reserve(1); walk(item.opt(i),depth+1) } }
                    ancestors.remove(item)
                }
                else -> fail()
            }
        }
        walk(value,0); return maximumBytes - remaining
    }
    internal fun boundedText(text: String) {
        var bytes = 0; var i = 0
        while (i < text.length) {
            val c = text[i++].code
            bytes += when {
                c < 128 -> 1
                c < 2048 -> 2
                c in 0xd800..0xdbff -> { if (i == text.length || text[i].code !in 0xdc00..0xdfff) fail(); i++; 4 }
                c in 0xdc00..0xdfff -> fail()
                else -> 3
            }
            if (bytes > MAXIMUM_BYTES) fail("limit")
        }
    }
    // Only immutable JSON scalars are retained. Containers are recursively detached after the
    // complete preflight; stringify/parse would narrow Double(2^63) on actual Android JSON.
    private fun copyValidated(value: Any?): Any = when (value) {
        null, JSONObject.NULL -> JSONObject.NULL
        is JSONObject -> JSONObject().also { target -> for (key in value.keys().asSequence()) target.put(key,copyValidated(value.get(key))) }
        is JSONArray -> JSONArray().also { target -> for (index in 0 until value.length()) target.put(copyValidated(value.opt(index))) }
        is String, is Boolean, is Number -> value
        else -> fail()
    }
    internal fun copyValue(value: Any): Any { preflight(value); return copyValidated(value) }
    internal fun copy(book: JSONObject): JSONObject = copyValue(book) as JSONObject
    internal fun encode(book: JSONObject): String { preflight(book); return canonical(book) }
    private val utf8KeyOrder = Comparator<String> { first, second ->
        var a = 0; var b = 0; var difference = 0
        while (a < first.length && b < second.length) {
            val left = Character.codePointAt(first,a); val right = Character.codePointAt(second,b)
            if (left != right) { difference = left.compareTo(right); break }
            a += Character.charCount(left); b += Character.charCount(right)
        }
        if (difference != 0) difference else (first.length-a).compareTo(second.length-b)
    }
    internal fun canonical(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"
        is JSONObject -> value.keys().asSequence().toList().sortedWith(utf8KeyOrder).joinToString(",","{","}") { JSONObject.quote(it)+":"+canonical(value.get(it)) }
        is JSONArray -> (0 until value.length()).joinToString(",","[","]") { canonical(value.opt(it)) }
        is String -> JSONObject.quote(value)
        is Boolean, is Number -> value.toString()
        else -> fail()
    }
    fun transform(incoming: JSONObject, live: JSONObject, newEpoch: UUID, restoredAtMillis: Long): JSONObject {
        if (restoredAtMillis < 0) fail()
        preflight(incoming); preflight(live)
        for (book in listOf(incoming,live)) for (domain in listOf("termine","aufgaben","kontakte","notizen")) if (book.has(domain)) {
            val records = book.opt(domain) as? JSONArray ?: fail()
            if (records.length() > 100_000) fail("limit")
            for (i in 0 until records.length()) if (records.opt(i) !is JSONObject) fail()
        }
        val epoch = newEpoch.toString()
        for (book in listOf(incoming,live)) {
            val meta = objectAt(book,"syncMetadaten"); val sync = objectAt(objectAt(book,"einstellungen"),"sync")
            if (listOf(book.opt("syncEpoch"),meta.opt("syncEpoch"),sync.opt("syncEpoch")).any { uuid(it) == newEpoch }) fail("invalid_epoch")
        }
        val frozenLive = copy(live)
        val result = copy(incoming); val meta = objectAt(result,"syncMetadaten"); val liveMeta = objectAt(frozenLive,"syncMetadaten")
        val deletes = JSONObject().also { d -> domains.forEach { d.put(it,JSONArray()) } }
        val tombstones = JSONArray(); val tree = JSONArray(); var count = 0; var bytes = 0
        val seen = mutableMapOf<String,MutableSet<String>>()
        fun append(values: JSONArray, container: String, target: JSONArray) {
            for (i in 0 until values.length()) {
                val row = values.opt(i) as? JSONObject ?: fail("unsupported_quarantine")
                val size = preflight(row, MAXIMUM_BYTES - bytes)
                val encoded = canonical(row)
                if (!seen.getOrPut(container) { mutableSetOf() }.add(encoded)) continue
                if (++count > MAXIMUM_QUARANTINE_ENTRIES || size > MAXIMUM_BYTES - bytes) fail("limit")
                bytes += size; target.put(copy(row))
            }
        }
        val quarantines = mutableListOf<Any>()
        for (m in listOf(liveMeta,meta)) if (m.has("quarantinedDeletes")) quarantines += m.get("quarantinedDeletes")
        quarantines += JSONObject().put("geloescht", if(incoming.has("geloescht")) incoming.get("geloescht") else JSONObject())
            .put("tombstones",if(incoming.has("tombstones")) incoming.get("tombstones") else JSONArray())
            .put("baumKontaktGeloescht",if(incoming.has("baumKontaktGeloescht")) incoming.get("baumKontaktGeloescht") else JSONArray())
        for (value in quarantines) {
            val q = value as? JSONObject ?: fail("unsupported_quarantine")
            if (q.keys().asSequence().any { it !in listOf("geloescht","tombstones","baumKontaktGeloescht") }) fail("unsupported_quarantine")
            val removed = if (!q.has("geloescht")) JSONObject() else q.opt("geloescht") as? JSONObject ?: fail("unsupported_quarantine")
            if (removed.keys().asSequence().any { it !in domains }) fail("unsupported_quarantine")
            for (domain in domains) append(rows(removed,domain),domain,deletes.getJSONArray(domain))
            append(rows(q,"tombstones"),"tombstones",tombstones); append(rows(q,"baumKontaktGeloescht"),"baumKontaktGeloescht",tree)
        }
        meta.put("quarantinedDeletes",JSONObject().put("geloescht",deletes).put("tombstones",tombstones).put("baumKontaktGeloescht",tree))
            .put("syncEpoch",epoch).put("ersteSyncLoeschungsfrei",true)
        if (meta.has("nextcloud")) meta.put("nextcloud",objectAt(meta,"nextcloud").also {
            it.remove("pendingCommitId"); it.remove("ausstehendeTransaktion"); it.put("transaktionen",JSONObject()) })
        result.put("syncMetadaten",meta).put("syncEpoch",epoch)
        result.remove("syncAbgleichBasis"); result.remove("syncAbgleichNachweis")
        result.put("geloescht",JSONObject().also { d -> domains.forEach { d.put(it,JSONArray()) } })
            .put("tombstones",JSONArray()).put("baumKontaktGeloescht",JSONArray())
        result.put("syncNachRestore",objectAt(result,"syncNachRestore").put("additiv",true).put("loeschungsfrei",true)
            .put("erstelltUtc",Instant.ofEpochMilli(restoredAtMillis).truncatedTo(ChronoUnit.SECONDS).toString()))
        for (domain in domains) if (result.has(domain)) {
            val records = result.opt(domain) as? JSONArray ?: fail()
            if (records.length() > 100_000) fail("limit")
            for (i in 0 until records.length()) { val row = records.opt(i) as? JSONObject ?: fail(); if (row.opt("sync") == true) row.put("geaendert",restoredAtMillis) }
        }
        val personal = objectAt(result,"personalSync"); val currentPersonal = objectAt(frozenLive,"personalSync")
        personal.put("actor_id",if(currentPersonal.has("actor_id")) currentPersonal.get("actor_id") else "")
            .put("custom_revision",if(currentPersonal.has("custom_revision")) currentPersonal.get("custom_revision") else 0)
            .put("custom_entities",if(currentPersonal.has("custom_entities")) currentPersonal.get("custom_entities") else JSONObject())
        personal.remove("custom_auto_hash"); result.put("personalSync",personal)
        val settings = objectAt(result,"einstellungen"); val sync = objectAt(settings,"sync")
        settings.put("sync",sync.put("syncEpoch",epoch).put("ersteSyncLoeschungsfrei",true))
        val liveAddresses = objectAt(objectAt(frozenLive,"einstellungen"),"adressen")
        settings.put("adressen",objectAt(settings,"adressen").put("smsSchedulingEnabled",liveAddresses.opt("smsSchedulingEnabled") == true))
        result.put("einstellungen",settings)
        if (result.has("smsPlanung")) {
            val plans = result.opt("smsPlanung") as? JSONArray ?: fail()
            for (i in 0 until plans.length()) {
                val row = plans.opt(i) as? JSONObject ?: fail()
                when(row.opt("status")) { "planned" -> row.put("status","paused"); "submitting" -> row.put("status","uncertain") }
            }
        }
        persistedEpoch(result); preflight(result)
        return result
    }
}
