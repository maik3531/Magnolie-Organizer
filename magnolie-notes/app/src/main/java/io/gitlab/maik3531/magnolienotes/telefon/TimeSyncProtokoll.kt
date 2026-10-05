package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeitKalender
import kotlinx.serialization.json.*

/** V7 codec; availability is advertised only once all transport gates are wired. */
object TimeSyncProtokoll {
    const val VERSION = 7
    const val SETTINGS = "personal_sync.time_settings"
    const val REQUEST = "personal_sync.time_request"
    const val BATCH = "personal_sync.time_batch"
    const val MAX_BODY = 192 * 1024
    val KINDS = setOf(SETTINGS, REQUEST, BATCH)
    private const val MAX_COUNTER = 9007199254740991L
    private val json = Json { encodeDefaults = true }
    private val recordFields = setOf("id", "startMinute", "endMinute", "pauseMinute", "pauseMinutes",
        "zone", "type", "note", "modifiedMs", "deleted", "clock")

    fun newSettings(enabled: Boolean = false, revision: Long = 1): JsonObject = buildJsonObject {
        put("format", VERSION); put("scope", "time_tracking"); put("enabled", enabled)
        put("revision", revision); put("epoch", java.util.UUID.randomUUID().toString())
    }.also(::settings)

    fun request(local: JsonObject, remote: JsonObject, trigger: String = "manual"): JsonObject {
        settings(local); settings(remote)
        return buildJsonObject {
            put("format", VERSION); put("trigger", trigger)
            put("sender_epoch", local.getValue("epoch")); put("receiver_epoch", remote.getValue("epoch"))
            put("sender_revision", local.getValue("revision")); put("receiver_revision", remote.getValue("revision"))
        }.also { validate(REQUEST, it, fromOrganizer = false) }
    }

    fun batches(local: JsonObject, remote: JsonObject, entries: List<Zeiteintrag>, trigger: String = "manual"): List<JsonObject> {
        require(entries.size <= 10000 && entries.map { it.id }.distinct().size == entries.size)
        val records = encodeRecords(entries)
        val header = request(local, remote, trigger)
        val packets = mutableListOf<JsonObject>()
        var current = emptyList<JsonElement>()
        fun packet(values: List<JsonElement>) = JsonObject(header + ("entries" to JsonArray(values)))
        for (entry in records) {
            val candidate = current + entry
            if (candidate.size > 32 || TelefonKanonisch.bytes(packet(candidate)).size > MAX_BODY) {
                if (current.isNotEmpty()) packets += packet(current)
                current = listOf(entry)
                validate(BATCH, packet(current), fromOrganizer = false)
            } else current = candidate
        }
        if (current.isNotEmpty() || packets.isEmpty()) packets += packet(current)
        return packets
    }

    fun settings(body: JsonObject) {
        TelefonNachrichten.exact(body, setOf("format", "scope", "enabled", "revision", "epoch"))
        require(number(body, "format") == VERSION.toLong() && text(body, "scope") == "time_tracking")
        boolean(body, "enabled")
        require(number(body, "revision") in 1L..MAX_COUNTER)
        TelefonNachrichten.uuid4(text(body, "epoch"))
    }

    fun acceptSettings(current: JsonObject?, incoming: JsonObject): JsonObject {
        settings(incoming)
        if (current != null) {
            settings(current)
            if (current == incoming) return current
            require(number(incoming, "revision") > number(current, "revision"))
            require(text(incoming, "epoch") != text(current, "epoch"))
        }
        return incoming
    }

    fun validate(kind: String, body: JsonObject, fromOrganizer: Boolean) {
        require(TelefonKanonisch.bytes(body).size <= MAX_BODY)
        if (kind == SETTINGS) { settings(body); return }
        val fields = setOf("format", "sender_epoch", "receiver_epoch", "sender_revision", "receiver_revision", "trigger")
        when (kind) {
            REQUEST -> TelefonNachrichten.exact(body, fields)
            BATCH -> TelefonNachrichten.exact(body, fields + "entries" + if (body.containsKey("calendar")) setOf("calendar") else emptySet())
            else -> error("Unknown time synchronization message")
        }
        require(number(body, "format") == VERSION.toLong())
        require(text(body, "trigger") in setOf("manual", "auto_wifi"))
        for (name in listOf("sender_epoch", "receiver_epoch")) TelefonNachrichten.uuid4(text(body, name))
        for (name in listOf("sender_revision", "receiver_revision")) require(number(body, name) in 1L..MAX_COUNTER)
        if (kind != BATCH) return
        val records = decodeRecords(body, fromOrganizer)
        require(records.size <= 32 && records.map { it.id }.distinct().size == records.size)
        if (body.containsKey("calendar")) {
            require(fromOrganizer)
            decodeCalendar(body.getValue("calendar").jsonObject)
        }
    }

    fun decodeRecords(body: JsonObject, fromOrganizer: Boolean = false): List<Zeiteintrag> = (body["entries"] as? JsonArray
        ?: error("Time records missing")).map { raw ->
        val value = raw as? JsonObject ?: error("Invalid time record")
        TelefonNachrichten.exact(value, recordFields + if (value.containsKey("pausePlan")) setOf("pausePlan") else emptySet())
        for (field in listOf("id", "zone", "type", "note")) {
            val text = text(value, field)
            require(Charsets.UTF_8.newEncoder().canEncode(text))
        }
        for (field in listOf("startMinute", "pauseMinutes", "modifiedMs")) number(value, field)
        for (field in listOf("endMinute", "pauseMinute")) if (value[field] != JsonNull) number(value, field)
        require(!boolean(value, "deleted") || fromOrganizer)
        val clock = value["clock"] as? JsonObject ?: error("Time clock missing")
        require(clock.isNotEmpty() && clock.size <= 32)
        for (actor in clock.keys) { TelefonNachrichten.uuid4(actor); require(number(clock, actor) in 1L..MAX_COUNTER) }
        value["pausePlan"]?.takeIf { it != JsonNull }?.let { plan(it as? JsonObject ?: error("Pause plan required")) }
        checkedRecord(json.decodeFromJsonElement(Zeiteintrag.serializer(), value), fromOrganizer)
    }

    fun encodeRecords(records: List<Zeiteintrag>, fromOrganizer: Boolean = false): JsonArray = JsonArray(records.map {
        checkedRecord(it, fromOrganizer); require(it.clock.isNotEmpty())
        json.encodeToJsonElement(Zeiteintrag.serializer(), it.copy(pausePlan = it.pausePlan?.let { value ->
            value.copy(replaced = value.replaced.sorted().toSet(), fixedEnds = value.fixedEnds.toSortedMap())
        }))
    })

    private fun checkedRecord(entry: Zeiteintrag, fromOrganizer: Boolean): Zeiteintrag {
        entry.validate()
        require(!entry.deleted || fromOrganizer)
        if (entry.deleted) require(entry.startMinute == 0L && entry.endMinute == 0L && entry.pauseMinute == null &&
            entry.pauseMinutes == 0L && entry.zone == "UTC" && entry.type.isEmpty() && entry.note.isEmpty() && entry.pausePlan == null)
        return entry
    }

    private fun plan(value: JsonObject) {
        TelefonNachrichten.exact(value, setOf("fixed", "manual", "replaced", "fixedEnds", "baseMinutes"))
        number(value, "baseMinutes")
        for ((key, limit) in listOf("fixed" to 16, "manual" to 10000)) {
            val intervals = value[key] as? JsonArray ?: error("Pause intervals required")
            require(intervals.size <= limit)
            intervals.forEach { raw ->
                val interval = raw as? JsonObject ?: error("Pause interval required")
                TelefonNachrichten.exact(interval, setOf("start", "end"))
                number(interval, "start"); number(interval, "end")
            }
        }
        val replaced = value["replaced"] as? JsonArray ?: error("Replaced occurrences required")
        require(replaced.size <= 60000)
        val starts = replaced.map { (it as? JsonPrimitive)?.takeIf { number -> !number.isString }?.longOrNull
            ?: error("Integer required") }
        require(starts == starts.distinct().sorted())
        val ends = value["fixedEnds"] as? JsonObject ?: error("Fixed pause endings required")
        require(ends.size <= 60000)
        ends.keys.forEach { key -> require(key.toLongOrNull()?.toString() == key); number(ends, key) }
    }

    fun decodeCalendar(value: JsonObject): ZeitKalender {
        TelefonNachrichten.exact(value, setOf("enabled", "country", "regions", "holidays"))
        boolean(value, "enabled"); text(value, "country")
        val regions = value["regions"] as? JsonArray ?: error("Regions missing")
        require(regions.all { it is JsonPrimitive && it.isString && Charsets.UTF_8.newEncoder().canEncode(it.content) })
        val days = value["holidays"] as? JsonArray ?: error("Holidays missing")
        for (raw in days) {
            val day = raw as? JsonObject ?: error("Invalid holiday")
            TelefonNachrichten.exact(day, setOf("date", "name", "country", "nationwide", "regions"))
            for (field in listOf("date", "name", "country")) text(day, field)
            boolean(day, "nationwide")
            require((day["regions"] as? JsonArray)?.all { it is JsonPrimitive && it.isString &&
                Charsets.UTF_8.newEncoder().canEncode(it.content) } == true)
        }
        return json.decodeFromJsonElement(ZeitKalender.serializer(), value).validate()
    }

    /** Uses only fresh controls from the authenticated connection, never cached availability alone. */
    fun allowed(body: JsonObject, local: JsonObject?, remote: JsonObject?, localOwn: Boolean, remoteOwn: Boolean,
                freshControls: Boolean, localVersions: List<Int>, remoteVersions: List<Int>): Boolean {
        if (!freshControls || !localOwn || !remoteOwn || VERSION !in localVersions || VERSION !in remoteVersions ||
            local == null || remote == null) return false
        return runCatching {
            settings(local); settings(remote)
            boolean(local, "enabled") && boolean(remote, "enabled") &&
                text(body, "sender_epoch") == text(remote, "epoch") && text(body, "receiver_epoch") == text(local, "epoch") &&
                number(body, "sender_revision") == number(remote, "revision") && number(body, "receiver_revision") == number(local, "revision")
        }.getOrDefault(false)
    }

    private fun text(body: JsonObject, key: String): String =
        (body[key] as? JsonPrimitive)?.takeIf { it.isString && Charsets.UTF_8.newEncoder().canEncode(it.content) }
            ?.content ?: error("String required")

    private fun number(body: JsonObject, key: String): Long =
        (body[key] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: error("Integer required")

    private fun boolean(body: JsonObject, key: String): Boolean =
        (body[key] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: error("Boolean required")
}
