package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.security.MessageDigest
import java.util.UUID

/** Current physical-phone membership; callers supply fresh authenticated owner/grant evidence. */
internal object PhoneContentScope {
    const val VERSION = 10
    const val MAX_MEMBERS = 50000
    private const val MIN_CHUNK = 32
    private const val MAX_CHUNK = 256
    private const val MAX_PARTS = (MAX_MEMBERS + MIN_CHUNK - 1) / MIN_CHUNK
    private const val MAX_REVISION = 9_007_199_254_740_991L
    private val idOrder = Comparator<String> { a, b ->
        val left = a.toByteArray(Charsets.UTF_8); val right = b.toByteArray(Charsets.UTF_8)
        var compared = 0
        for (index in 0 until minOf(left.size, right.size)) {
            compared = (left[index].toInt() and 255).compareTo(right[index].toInt() and 255)
            if (compared != 0) break
        }
        if (compared != 0) compared else left.size.compareTo(right.size)
    }
    private fun text(body: JsonObject, field: String): String = (body[field] as? JsonPrimitive)
        ?.takeIf { it.isString }?.content ?: error("Scope text missing")
    private fun number(body: JsonObject, field: String): Long {
        val raw = body[field] as? JsonPrimitive ?: error("Scope number missing")
        require(!raw.isString && Regex("0|[1-9][0-9]*").matches(raw.content))
        return requireNotNull(raw.longOrNull)
    }
    private fun identifier(value: String): String {
        require(value.isNotEmpty() && value == value.trim() && '\u0000' !in value)
        require(Charsets.UTF_8.newEncoder().canEncode(value) && value.toByteArray(Charsets.UTF_8).size <= 160)
        return value
    }
    private fun header(body: JsonObject) {
        require(number(body, "format") == VERSION.toLong() && number(body, "revision") in 1..MAX_REVISION)
        TelefonNachrichten.uuid4(text(body, "epoch"))
    }
    private fun digest(members: JsonObject): String = MessageDigest.getInstance("SHA-256")
        .digest(TelefonKanonisch.bytes(members)).joinToString("") { "%02x".format(it.toInt() and 255) }
    private fun ids(body: JsonObject, field: String): List<String> {
        val raw = body[field] as? JsonArray ?: error("Scope identities missing")
        val values = raw.map { identifier((it as? JsonPrimitive)?.takeIf { value -> value.isString }?.content
            ?: error("Invalid scope identity")) }
        require(values == values.distinct().sortedWith(idOrder))
        return values
    }
    fun validate(manifest: JsonObject): JsonObject {
        TelefonNachrichten.exact(manifest, setOf("format", "epoch", "revision", "scope_hash", "members")); header(manifest)
        val members = manifest["members"] as? JsonObject ?: error("Scope members missing")
        TelefonNachrichten.exact(members, setOf("notes", "tasks"))
        require(ids(members, "notes").size + ids(members, "tasks").size <= MAX_MEMBERS)
        require(text(manifest, "scope_hash") == digest(members))
        return manifest
    }
    fun create(notes: Collection<String>, tasks: Collection<String>, revision: Long = 1, epoch: String = UUID.randomUUID().toString()): JsonObject {
        fun values(input: Collection<String>) = JsonArray(input.map(::identifier).distinct().sortedWith(idOrder).map(::JsonPrimitive))
        val members = buildJsonObject { put("notes", values(notes)); put("tasks", values(tasks)) }
        return validate(buildJsonObject { put("format", VERSION); put("epoch", epoch); put("revision", revision)
            put("scope_hash", digest(members)); put("members", members) })
    }
    fun advance(current: JsonObject, notes: Collection<String>, tasks: Collection<String>): JsonObject {
        validate(current); val candidate = create(notes, tasks, number(current, "revision"))
        if (candidate["members"] == current["members"]) return current
        return validate(JsonObject(candidate + ("revision" to JsonPrimitive(number(current, "revision") + 1))))
    }
    fun reference(manifest: JsonObject): JsonObject {
        validate(manifest)
        return buildJsonObject { put("scope_epoch", manifest.getValue("epoch")); put("scope_revision", manifest.getValue("revision"));
            put("scope_hash", manifest.getValue("scope_hash")) }
    }
    fun requireCurrent(body: JsonObject, manifest: JsonObject) {
        val expected = reference(manifest)
        require(number(body, "scope_revision") == number(expected, "scope_revision") &&
            text(body, "scope_epoch") == text(expected, "scope_epoch") && text(body, "scope_hash") == text(expected, "scope_hash"))
    }
    fun validatePart(body: JsonObject): JsonObject {
        TelefonNachrichten.exact(body, setOf("format", "epoch", "revision", "scope_hash", "part", "parts", "members")); header(body)
        require(Regex("[0-9a-f]{64}").matches(text(body, "scope_hash")))
        require(number(body, "parts") in 1..MAX_PARTS && number(body, "part") in 0 until number(body, "parts"))
        val members = body["members"] as? JsonArray ?: error("Scope members missing")
        require(members.size <= MAX_CHUNK)
        val entries = members.map { raw ->
            val member = raw as? JsonObject ?: error("Invalid scope member")
            TelefonNachrichten.exact(member, setOf("kind", "id"))
            val kind = text(member, "kind"); require(kind in setOf("note", "task"))
            kind to identifier(text(member, "id"))
        }
        val entryOrder = Comparator<Pair<String, String>> { a, b -> a.first.compareTo(b.first).takeIf { it != 0 } ?: idOrder.compare(a.second, b.second) }
        require(entries == entries.distinct().sortedWith(entryOrder))
        require(TelefonKanonisch.bytes(body).size <= 192 * 1024)
        return body
    }
    fun chunks(manifest: JsonObject, size: Int = MAX_CHUNK): List<JsonObject> {
        validate(manifest); require(size in MIN_CHUNK..MAX_CHUNK)
        val members = manifest.getValue("members").jsonObject
        val entries = listOf("note" to "notes", "task" to "tasks").flatMap { (kind, bucket) ->
            ids(members, bucket).map { id -> buildJsonObject { put("kind", kind); put("id", id) } } }
        val count = maxOf(1, (entries.size + size - 1) / size)
        return (0 until count).map { index -> validatePart(buildJsonObject {
            for (field in listOf("format", "epoch", "revision", "scope_hash")) put(field, manifest.getValue(field))
            put("part", index); put("parts", count)
            put("members", JsonArray(entries.subList(index * size, minOf((index + 1) * size, entries.size))))
        }) }
    }
    fun assemble(pieces: List<JsonObject>): JsonObject {
        val byIndex = mutableMapOf<Long, JsonObject>(); var header: JsonObject? = null
        for (piece in pieces) {
            validatePart(piece)
            val shape = JsonObject(listOf("format", "epoch", "revision", "scope_hash", "parts").associateWith(piece::getValue))
            require(header == null || header == shape); header = shape
            val index = number(piece, "part"); require(byIndex[index] == null || byIndex[index] == piece)
            byIndex[index] = piece
        }
        val current = requireNotNull(header); require(byIndex.size.toLong() == number(current, "parts"))
        val notes = mutableListOf<JsonElement>(); val tasks = mutableListOf<JsonElement>()
        for (index in 0 until number(current, "parts")) for (raw in byIndex.getValue(index).getValue("members").jsonArray) {
            val member = raw.jsonObject; (if (text(member, "kind") == "note") notes else tasks).add(member.getValue("id"))
        }
        val members = buildJsonObject { put("notes", JsonArray(notes)); put("tasks", JsonArray(tasks)) }
        return validate(JsonObject(current - "parts" + ("members" to members)))
    }
    fun filterRecords(records: List<JsonObject>, manifest: JsonObject): List<JsonObject> {
        validate(manifest); val members = manifest.getValue("members").jsonObject
        val notes = ids(members, "notes").toSet(); val tasks = ids(members, "tasks").toSet()
        val selected = mutableSetOf<Pair<String, String>>(); val notebooks = mutableSetOf<String>()
        for (record in records) {
            val kind = text(record, "kind"); val id = text(record, "id")
            if (text(record, "state") != "live" || !(kind == "note" && id in notes || kind == "task" && id in tasks)) continue
            selected.add(kind to id)
            if (kind == "note") (record["value"] as? JsonObject)?.get("notebook_id")?.let { raw ->
                val book = (raw as? JsonPrimitive)?.takeIf { it.isString }?.content.orEmpty()
                if (book.isNotEmpty()) notebooks.add(identifier(book))
            }
        }
        return records.filter { record -> text(record, "state") == "live" &&
            ((text(record, "kind") to text(record, "id")) in selected || text(record, "kind") == "notebook" && text(record, "id") in notebooks) }
    }
}
