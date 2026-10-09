package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Common function preferences. Authentication, ownership and OS rights are caller gates. */
internal object SharedSyncSettings {
    const val VERSION = 9
    const val KIND = "personal_sync.shared_settings"
    private const val MAX_COUNTER = 9_007_199_254_740_991L
    private val defaults = linkedMapOf("content_mode" to JsonPrimitive("phone_scope"),
        "auto_mode" to JsonPrimitive("manual"), "skip_deletions" to JsonPrimitive(true),
        "custom_enabled" to JsonPrimitive(false), "time_enabled" to JsonPrimitive(false),
        "time_mode" to JsonPrimitive("phone_import"))
    private val enums = mapOf("content_mode" to setOf("phone_import", "phone_scope", "two_way"),
        "time_mode" to setOf("phone_import", "two_way"), "auto_mode" to setOf("manual", "wifi", "connection"))

    private fun value(field: String, value: JsonElement): JsonPrimitive {
        require(field in defaults)
        val primitive = value as? JsonPrimitive ?: error("Invalid common function value")
        val modes = enums[field]
        if (modes != null) require(primitive.isString && primitive.content in modes)
        else require(!primitive.isString && primitive.booleanOrNull != null)
        return primitive
    }

    private fun counter(edit: JsonObject): Long {
        val raw = edit["counter"] as? JsonPrimitive ?: error("Missing setting counter")
        require(!raw.isString && Regex("0|[1-9][0-9]*").matches(raw.content))
        return requireNotNull(raw.longOrNull).also { require(it in 0..MAX_COUNTER) }
    }

    fun validate(body: JsonObject): JsonObject {
        TelefonNachrichten.exact(body, setOf("format", "settings"))
        val format = body["format"] as? JsonPrimitive ?: error("Missing shared settings format")
        require(!format.isString && format.content == VERSION.toString())
        val fields = body["settings"] as? JsonObject ?: error("Missing function settings")
        require(fields.size in 1..defaults.size)
        for ((field, raw) in fields) {
            require(field in defaults)
            val edits = raw as? JsonObject ?: error("Invalid setting register")
            require(edits.size in 1..2)
            for ((origin, rawEdit) in edits) {
                TelefonNachrichten.uuid4(origin)
                val edit = rawEdit as? JsonObject ?: error("Invalid setting edit")
                TelefonNachrichten.exact(edit, setOf("counter", "value"))
                counter(edit); value(field, edit.getValue("value"))
            }
        }
        return body
    }

    fun create(localActor: String, initial: Map<String, JsonElement> = emptyMap()): JsonObject {
        TelefonNachrichten.uuid4(localActor)
        val values = defaults.toMutableMap()
        initial.forEach { (field, raw) -> values[field] = value(field, raw) }
        return validate(buildJsonObject {
            put("format", VERSION)
            put("settings", JsonObject(values.mapValues { (_, raw) -> buildJsonObject {
                put(localActor, buildJsonObject { put("counter", 0); put("value", raw) })
            } }))
        })
    }

    fun effective(body: JsonObject): JsonObject {
        validate(body)
        return JsonObject(body.getValue("settings").jsonObject.mapValues { (field, raw) ->
            val edits = raw.jsonObject.values.map { it.jsonObject }
            val newest = edits.maxOf(::counter)
            val values = edits.filter { counter(it) == newest }.map { value(field, it.getValue("value")) }
            when (field) {
                "content_mode" -> JsonPrimitive(listOf("phone_import", "phone_scope", "two_way").first { mode -> values.any { it.content == mode } })
                "time_mode" -> JsonPrimitive(if (values.any { it.content == "phone_import" }) "phone_import" else "two_way")
                "custom_enabled", "time_enabled" -> JsonPrimitive(values.all { it.boolean })
                "skip_deletions" -> JsonPrimitive(values.any { it.boolean })
                else -> JsonPrimitive((if (newest == 0L) listOf("wifi", "manual", "connection") else listOf("manual", "wifi", "connection"))
                    .first { mode -> values.any { it.content == mode } })
            }
        })
    }

    private fun scoped(body: JsonObject, localActor: String, peerActor: String) {
        validate(body); TelefonNachrichten.uuid4(localActor); TelefonNachrichten.uuid4(peerActor)
        require(localActor != peerActor)
        require(body.getValue("settings").jsonObject.values.all { raw -> raw.jsonObject.keys.all { it == localActor || it == peerActor } })
    }

    fun change(body: JsonObject, localActor: String, peerActor: String, field: String, raw: JsonElement): JsonObject {
        scoped(body, localActor, peerActor)
        val value = value(field, raw)
        val fields = body.getValue("settings").jsonObject.toMutableMap()
        val edits = (fields[field] as? JsonObject)?.toMutableMap() ?: mutableMapOf()
        val next = edits.values.maxOfOrNull { counter(it.jsonObject) }?.plus(1) ?: 1L
        require(next <= MAX_COUNTER)
        edits[localActor] = buildJsonObject { put("counter", next); put("value", value) }
        fields[field] = JsonObject(edits)
        return validate(JsonObject(body + ("settings" to JsonObject(fields))))
    }

    fun merge(body: JsonObject, incoming: JsonObject, localActor: String, peerActor: String): JsonObject {
        scoped(body, localActor, peerActor); scoped(incoming, localActor, peerActor)
        val fields = body.getValue("settings").jsonObject.toMutableMap()
        for ((field, raw) in incoming.getValue("settings").jsonObject) {
            val target = (fields[field] as? JsonObject)?.toMutableMap() ?: mutableMapOf()
            for ((origin, rawEdit) in raw.jsonObject) {
                val edit = rawEdit.jsonObject; val previous = target[origin]?.jsonObject
                if (origin == localActor) {
                    require(previous != null && counter(edit) <= counter(previous))
                    require(counter(edit) != counter(previous) || edit == previous)
                    continue
                }
                if (previous != null) {
                    if (counter(edit) < counter(previous)) continue
                    require(counter(edit) != counter(previous) || edit == previous)
                }
                target[origin] = JsonObject(edit.toMap())
            }
            fields[field] = JsonObject(target)
        }
        return validate(JsonObject(body + ("settings" to JsonObject(fields))))
    }
}
