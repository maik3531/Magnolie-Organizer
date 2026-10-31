package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.baum.KontaktDaten
import io.gitlab.maik3531.magnolienotes.baum.KontaktSync
import io.gitlab.maik3531.magnolienotes.baum.KontaktWert
import kotlinx.serialization.json.*

/** Explicit phone/email value resource; other contact fields use their own supported paths. */
object ContactValueWrite {
    const val VERSION = 19
    internal const val RUNTIME_ENABLED = true
    const val MAX_BYTES = 128 * 1024
    val FIELDS = setOf("telefone", "emailEintraege")
    fun allowed(peer: TelefonPeer?, permission: Boolean): Boolean = ContactRead.allowed(peer, permission) &&
        peer?.contacts_write_enabled == true && VERSION in peer.remote_device_status_versions
    private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
    private fun text(node: JsonElement?, max: Int, empty: Boolean = false): String {
        val value = (node as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error("invalid_contact_value")
        require((empty || value.isNotBlank()) && value.codePointCount(0, value.length) <= max &&
            value.none(Char::isISOControl) && value.codePoints().noneMatch { it in 0xD800..0xDFFF })
        return value
    }
    fun fieldNames(value: JsonObject): Set<String> {
        val array = value["field_names"] as? JsonArray ?: error("invalid_contact_fields")
        val names = array.map { text(it, 32) }
        require(names.isNotEmpty() && names.size <= FIELDS.size && names.toSet().size == names.size && FIELDS.containsAll(names))
        return names.toSet()
    }
    fun fields(value: JsonObject): Map<String, List<KontaktWert>> {
        val fields = value["fields"] as? JsonObject ?: error("invalid_contact_fields")
        require(fields.isNotEmpty() && FIELDS.containsAll(fields.keys))
        return fields.mapValues { (field, element) ->
            val array = element as? JsonArray ?: error("invalid_contact_values")
            require(array.size <= 100)
            val entries = array.map { node ->
                val entry = node as? JsonObject ?: error("invalid_contact_value")
                require(entry.keys == setOf("art", "wert"))
                val kind = text(entry["art"], 32)
                require(kind in setOf("privat", "arbeit", "mobil", "sonstige"))
                KontaktWert(kind, text(entry["wert"], 4096))
            }
            val keys = entries.map { if (field == "telefone") KontaktSync.normalWert(it.wert) else KontaktSync.normalEmail(it.wert) }
            require(keys.toSet().size == entries.size)
            entries
        }
    }
    private fun header(value: JsonObject) {
        require(value["version"] == JsonPrimitive(VERSION) && uuid.matches(value.string("request_id")) &&
            ContactRead.validUid(text(value["uid"], 256)) && value.string("action") in setOf("prepare", "apply"))
        require(TelefonKanonisch.bytes(value).size <= MAX_BYTES)
    }
    fun validateRequest(value: JsonObject) {
        header(value)
        require(value.keys == setOf("version", "request_id", "action", "uid") +
            if (value.string("action") == "prepare") setOf("field_names") else setOf("token", "fields"))
        if (value.string("action") == "prepare") fieldNames(value)
        else { require(uuid.matches(value.string("token"))); fields(value) }
    }
    fun values(contact: KontaktDaten, names: Set<String>): JsonObject = buildJsonObject {
        require(names.isNotEmpty() && FIELDS.containsAll(names))
        for (name in names) put(name, JsonArray((if (name == "telefone") contact.telefone else contact.emailEintraege).map {
            buildJsonObject { put("art", it.art); put("wert", it.wert) }
        }))
    }
    fun report(request: JsonObject, token: String, contact: KontaktDaten, names: Set<String>, account: JsonObject): JsonObject = buildJsonObject {
        put("version", VERSION); put("request_id", request.getValue("request_id")); put("action", request.getValue("action"))
        put("uid", request.getValue("uid")); put("token", token); put("account", account)
        put("state", if (request.string("action") == "prepare") "prepared" else "saved")
        put("fields", values(contact, names))
    }.also(::validateReport)
    fun validateReport(value: JsonObject) {
        header(value)
        require(value.keys == setOf("version", "request_id", "action", "uid", "token", "account", "state", "fields"))
        require(uuid.matches(value.string("token")) && value.string("state") ==
            if (value.string("action") == "prepare") "prepared" else "saved")
        fields(value)
        val account = value["account"] as? JsonObject ?: error("invalid_contact_account")
        require(account.keys == setOf("name", "type", "data_set"))
        account.values.forEach { text(it, 256, empty = true) }
    }
}
