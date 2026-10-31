package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.baum.KontaktSync
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Separate opt-in resource. Version 5 remains a read-only contact resource. */
object ContactGroupWrite {
    const val VERSION = 17
    const val MAX_BYTES = 128 * 1024
    private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

    fun allowed(peer: TelefonPeer?, permission: Boolean): Boolean =
        ContactRead.allowed(peer, permission) && peer?.contact_groups_write_enabled == true && VERSION in peer.remote_device_status_versions

    private fun uid(value: String) = ContactRead.validUid(value) && value.codePoints().noneMatch { it in 0xD800..0xDFFF }

    fun names(value: JsonObject, field: String, limit: Int = 100): List<String> {
        val array = value[field] as? JsonArray ?: error("invalid_contact_groups")
        require(array.size <= limit)
        val names = array.map { node ->
            val text = (node as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error("invalid_contact_groups")
            require(text.isNotBlank() && text.codePointCount(0, text.length) <= 256 && text.none(Char::isISOControl))
            require(text.codePoints().noneMatch { it in 0xD800..0xDFFF })
            text
        }
        require(KontaktSync.normalisiereGruppen(names).size == names.size)
        return names
    }

    fun validateRequest(value: JsonObject) {
        val action = value.string("action")
        require(action in setOf("prepare", "apply"))
        require(value.keys == setOf("version", "request_id", "action", "uid") +
            if (action == "apply") setOf("token", "groups") else emptySet())
        require(value["version"] == JsonPrimitive(VERSION) && uuid.matches(value.string("request_id")) && uid(value.string("uid")))
        if (action == "apply") { require(uuid.matches(value.string("token"))); names(value, "groups") }
        require(TelefonKanonisch.bytes(value).size <= MAX_BYTES)
    }

    fun report(request: JsonObject, token: String, groups: List<String>, catalog: List<String> = emptyList(),
               account: JsonObject = buildJsonObject { put("name", ""); put("type", ""); put("data_set", "") }): JsonObject = buildJsonObject {
        put("version", VERSION); put("request_id", request.getValue("request_id")); put("action", request.getValue("action"))
        put("uid", request.getValue("uid")); put("token", token)
        put("state", if (request.string("action") == "prepare") "prepared" else "saved")
        put("groups", JsonArray(groups.map(::JsonPrimitive))); put("catalog", JsonArray(catalog.map(::JsonPrimitive)))
        put("account", account)
    }.also(::validateReport)

    fun validateReport(value: JsonObject) {
        require(value.keys == setOf("version", "request_id", "action", "uid", "token", "state", "groups", "catalog", "account"))
        require(value["version"] == JsonPrimitive(VERSION) && uuid.matches(value.string("request_id")) &&
            uuid.matches(value.string("token")) && uid(value.string("uid")))
        require(value.string("action") in setOf("prepare", "apply") &&
            value.string("state") == if (value.string("action") == "prepare") "prepared" else "saved")
        names(value, "groups"); val catalog = names(value, "catalog", 1000)
        require(value.string("action") == "prepare" || catalog.isEmpty())
        val account = value["account"] as? JsonObject ?: error("invalid_contact_account")
        require(account.keys == setOf("name", "type", "data_set"))
        account.values.forEach { node ->
            val text = (node as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error("invalid_contact_account")
            require(text.codePointCount(0, text.length) <= 256 && text.none(Char::isISOControl) &&
                text.codePoints().noneMatch { it in 0xD800..0xDFFF })
        }
        require(TelefonKanonisch.bytes(value).size <= MAX_BYTES)
    }
}
