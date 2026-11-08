package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Separate media intent; no personal-data preferences, OS rights or data grants. */
internal object MediaSyncSettings {
    const val DISCOVERY_VERSION = 23
    const val VERSION = 1
    const val KIND = "file_transfer.shared_settings"
    const val START_KIND = "file_transfer.sync_request"
    const val RESULT_KIND = "file_transfer.sync_result"

    fun validateStart(body: JsonObject) {
        TelefonNachrichten.exact(body, setOf("format", "settings"))
        require(body["format"] == JsonPrimitive(1))
        val settings = body.getValue("settings").jsonObject
        validate(settings)
        require(settings.getValue("settings").jsonObject.size == fields.size)
    }

    fun validateResult(body: JsonObject) {
        TelefonNachrichten.exact(body, setOf("format", "request_id", "state"))
        require(body["format"] == JsonPrimitive(1))
        TelefonNachrichten.uuid4(body.string("request_id"))
        require(body.string("state") in setOf("content_pass", "review", "held"))
    }
    private val fields = linkedMapOf("photos_enabled" to "custom_enabled", "videos_enabled" to "time_enabled",
        "auto_mode" to "auto_mode", "skip_deletions" to "skip_deletions", "collection_mode" to "content_mode", "direction" to "content_mode",
        "enabled" to "custom_enabled", "photos_only" to "skip_deletions")

    private fun settingValue(field: String, raw: JsonElement, toRegisters: Boolean): JsonElement {
        val modes = when (field) {
            "collection_mode" -> mapOf("phone_inventory" to "phone_scope", "entire_collection" to "two_way", "import_only" to "phone_import")
            "direction" -> mapOf("phone_to_pc" to "phone_import", "two_way" to "two_way", "pc_to_phone" to "phone_scope")
            "auto_mode" -> mapOf("manual" to "manual", "wifi" to "wifi")
            else -> return raw
        }
        val value = raw as? JsonPrimitive ?: error("Invalid media setting mode")
        require(value.isString)
        val translated = if (toRegisters) modes[value.content] else modes.entries.singleOrNull { it.value == value.content }?.key
        return JsonPrimitive(requireNotNull(translated))
    }

    private fun settingRegister(field: String, raw: JsonElement, toRegisters: Boolean): JsonObject {
        val edits = raw as? JsonObject ?: error("Invalid media register")
        return JsonObject(edits.mapValues { (_, rawEdit) ->
            val edit = rawEdit as? JsonObject ?: error("Invalid media setting edit")
            JsonObject(edit + ("value" to settingValue(field, edit.getValue("value"), toRegisters)))
        })
    }

    private fun registers(field: String, raw: JsonElement): JsonObject {
        require(field in fields)
        // Registers are evaluated individually: activation and photo selection
        // must never share an edit clock just because both are Boolean values.
        return SharedSyncSettings.validate(buildJsonObject {
            put("format", SharedSyncSettings.VERSION)
            put("settings", buildJsonObject { put(fields.getValue(field), settingRegister(field, raw, true)) })
        })
    }

    fun validate(body: JsonObject): JsonObject {
        TelefonNachrichten.exact(body, setOf("format", "settings"))
        require(body["format"] == JsonPrimitive(VERSION))
        val values = body["settings"] as? JsonObject ?: error("Missing media settings")
        require(values.size in 1..fields.size && values.keys.all { it in fields })
        values.forEach { (field, raw) -> registers(field, raw) }
        return body
    }

    private fun scoped(body: JsonObject, localActor: String, peerActor: String, complete: Boolean) {
        validate(body)
        val values = body.getValue("settings").jsonObject
        require(!complete || values.size == fields.size)
        values.forEach { (field, raw) ->
            val register = registers(field, raw)
            SharedSyncSettings.merge(register, register, localActor, peerActor)
        }
    }

    fun create(localActor: String): JsonObject {
        val defaults = linkedMapOf("enabled" to JsonPrimitive(false), "photos_enabled" to JsonPrimitive(true),
            "videos_enabled" to JsonPrimitive(false), "collection_mode" to JsonPrimitive("phone_inventory"),
            "auto_mode" to JsonPrimitive("manual"), "skip_deletions" to JsonPrimitive(false), "direction" to JsonPrimitive("phone_to_pc"),
            "photos_only" to JsonPrimitive(false))
        return validate(buildJsonObject {
            put("format", VERSION)
            put("settings", JsonObject(defaults.mapValues { (_, value) -> buildJsonObject {
                put(localActor, buildJsonObject { put("counter", 0); put("value", value) })
            } }))
        })
    }

    /** Protected stored records only; never complete a partial wire snapshot.
     * Passive projection preserves every prior register and does not write. */
    fun normalizeStored(body: JsonObject, localActor: String, peerActor: String): JsonObject {
        scoped(body, localActor, peerActor, false)
        val values = body.getValue("settings").jsonObject
        require(values.keys == fields.keys || values.keys == fields.keys - "photos_only")
        val normalized = if ("photos_only" in values) body else JsonObject(body + ("settings" to JsonObject(values +
            ("photos_only" to buildJsonObject { put(localActor, buildJsonObject { put("counter", 0); put("value", false) }) }))))
        scoped(normalized, localActor, peerActor, true)
        return normalized
    }

    fun effective(body: JsonObject): JsonObject {
        validate(body)
        val values = body.getValue("settings").jsonObject.mapValues { (field, raw) ->
            settingValue(field, SharedSyncSettings.effective(registers(field, raw)).getValue(fields.getValue(field)), false)
        }.toMutableMap()
        body.getValue("settings").jsonObject["auto_mode"]?.jsonObject?.let { modes ->
            val newest = modes.values.maxOf { it.jsonObject.getValue("counter").jsonPrimitive.long }
            values["auto_mode"] = JsonPrimitive(if (modes.values.any { edit ->
                edit.jsonObject.getValue("counter").jsonPrimitive.long == newest &&
                    edit.jsonObject.getValue("value") == JsonPrimitive("manual") }) "manual" else "wifi")
        }
        // Import never exports; retain the independently stored direction so
        // switching scope does not rewrite the user's choice or edit history.
        if (values["collection_mode"] == JsonPrimitive("import_only") && "direction" in values) values["direction"] = JsonPrimitive("phone_to_pc")
        return JsonObject(values)
    }

    fun change(body: JsonObject, localActor: String, peerActor: String, field: String, value: JsonElement): JsonObject {
        require(field in fields)
        scoped(body, localActor, peerActor, true)
        val values = body.getValue("settings").jsonObject.toMutableMap()
        val changed = SharedSyncSettings.change(registers(field, values.getValue(field)), localActor, peerActor,
            fields.getValue(field), settingValue(field, value, true))
        values[field] = settingRegister(field, changed.getValue("settings").jsonObject.getValue(fields.getValue(field)), false)
        return validate(JsonObject(body + ("settings" to JsonObject(values))))
    }

    fun transferRequestedFor(body: JsonObject, mediaType: String, toPhone: Boolean): Boolean {
        if (!requestedFor(body, mediaType)) return false
        val direction = effective(body).string("direction")
        return direction == "two_way" || direction == (if (toPhone) "pc_to_phone" else "phone_to_pc")
    }

    fun requestedFor(body: JsonObject, mediaType: String): Boolean {
        require(body["settings"]?.jsonObject?.size == fields.size && mediaType in setOf("images", "video"))
        val values = effective(body)
        return values.getValue("enabled").jsonPrimitive.boolean &&
            values.getValue(if (mediaType == "images") "photos_enabled" else "videos_enabled").jsonPrimitive.boolean
    }

    fun merge(body: JsonObject, incoming: JsonObject, localActor: String, peerActor: String): JsonObject =
        mergeOwned(body, incoming, localActor, peerActor, false)

    fun mergeCurrentChoices(body: JsonObject, incoming: JsonObject, localActor: String, peerActor: String): JsonObject =
        mergeOwned(body, incoming, localActor, peerActor, true)

    private fun mergeOwned(body: JsonObject, incoming: JsonObject, localActor: String, peerActor: String, currentChoices: Boolean): JsonObject {
        scoped(body, localActor, peerActor, true); scoped(incoming, localActor, peerActor, false)
        val values = body.getValue("settings").jsonObject.toMutableMap()
        incoming.getValue("settings").jsonObject.forEach { (field, raw) ->
            val before = registers(field, values.getValue(field)); val next = registers(field, raw)
            val merged = if (currentChoices) SharedSyncSettings.mergeCurrentChoices(before, next, localActor, peerActor)
                else SharedSyncSettings.merge(before, next, localActor, peerActor)
            values[field] = settingRegister(field, merged.getValue("settings").jsonObject.getValue(fields.getValue(field)), false)
        }
        return validate(JsonObject(body + ("settings" to JsonObject(values))))
    }
}
