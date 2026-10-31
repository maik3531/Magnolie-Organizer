package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.text.Normalizer

/** Explicit group-title operation, separate from per-contact memberships. */
object ContactGroupTitleWrite {
    const val VERSION = 20
    const val RUNTIME_ENABLED = true
    const val MAX_BYTES = 16 * 1024
    private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
    fun allowed(peer: TelefonPeer?, permission: Boolean): Boolean = ContactRead.allowed(peer, permission) &&
        peer?.contacts_write_enabled == true && VERSION in peer.remote_device_status_versions
    private fun text(node: JsonElement?, max: Int, empty: Boolean = false): String {
        val value = (node as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error("invalid_group_title")
        require((empty || value.isNotBlank()) && value.codePointCount(0, value.length) <= max && value.none(Char::isISOControl) &&
            value.codePoints().noneMatch { it in 0xD800..0xDFFF })
        return value
    }
    private fun header(value: JsonObject) {
        require(value["version"] == JsonPrimitive(VERSION) && uuid.matches(value.string("request_id")) &&
            ContactRead.validUid(text(value["uid"], 256)) && value.string("action") in setOf("prepare", "apply", "inspect"))
        val old = text(value["old_title"], 256); val new = text(value["new_title"], 256)
        require(old != new && listOf(old, new).all { it == Normalizer.normalize(it.trim(), Normalizer.Form.NFC) })
        require(TelefonKanonisch.bytes(value).size <= MAX_BYTES)
    }
    fun validateRequest(value: JsonObject) {
        header(value)
        require(value.keys == setOf("version", "request_id", "action", "uid", "old_title", "new_title") +
            when (value.string("action")) { "apply" -> setOf("token"); "inspect" -> setOf("group_id", "account"); else -> emptySet() })
        if (value.string("action") == "apply") require(uuid.matches(value.string("token")))
        if (value.string("action") == "inspect") identityFields(value)
    }
    private fun identityFields(value: JsonObject) {
        val id = text(value["group_id"], 19)
        require(Regex("[1-9][0-9]{0,18}").matches(id) && id.toLongOrNull()?.let { it > 0 } == true)
        val account = value["account"] as? JsonObject ?: error("invalid_contact_account")
        require(account.keys == setOf("name", "type", "data_set")); account.values.forEach { text(it, 256, empty = true) }
    }
    fun validateReport(value: JsonObject) {
        header(value)
        val inspect = value.string("action") == "inspect"
        require(value.keys == setOf("version", "request_id", "action", "uid", "old_title", "new_title", "state", "group_id", "account", "group_identity") +
            if (inspect) setOf("current_title") else setOf("token"))
        identityFields(value)
        require(Regex("[a-f0-9]{64}").matches(text(value["group_identity"], 64)))
        require(value.string("state") == if (inspect) "current" else if (value.string("action") == "prepare") "prepared" else "saved")
        if (inspect) text(value["current_title"], 256) else require(uuid.matches(value.string("token")))
    }
    fun report(request: JsonObject, token: String, groupId: Long, account: JsonObject, identity: String): JsonObject = buildJsonObject {
        for (field in listOf("version", "request_id", "action", "uid", "old_title", "new_title")) put(field, request.getValue(field))
        put("token", token); put("group_id", groupId.toString()); put("account", account)
        put("group_identity", identity)
        put("state", if (request.string("action") == "prepare") "prepared" else "saved")
    }.also(::validateReport)
    fun inspection(request: JsonObject, groupId: Long, account: JsonObject, identity: String, title: String): JsonObject = buildJsonObject {
        for (field in listOf("version", "request_id", "action", "uid", "old_title", "new_title")) put(field, request.getValue(field))
        put("group_id", groupId.toString()); put("account", account); put("group_identity", identity)
        put("state", "current"); put("current_title", title)
    }.also(::validateReport)
}
