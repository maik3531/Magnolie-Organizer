package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Optional, explicitly authorized read-only device-status resource, version 5. */
object ContactRead {
    const val VERSION = 5
    const val PROFILE_VERSION = 7
    const val PROFILE_DIAGNOSTIC_VERSION = 8
    val diagnosticStages = setOf("canonical_header", "marked_header", "data", "photo", "finish")
    val diagnosticOutcomes = setOf("ok", "no_cursor", "empty", "ambiguous", "invalid_identity", "permission_denied",
        "unsupported_or_invalid", "provider_changed", "too_large", "no_profile", "provider_failure")
    const val PAGE_SIZE = 128
    const val MAX_CONTACTS = 10_000
    const val MAX_CARD_BYTES = 96 * 1024
    const val MAX_REPORT_BYTES = 128 * 1024
    private val uuid4 = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

    fun allowed(peer: TelefonPeer?, permission: Boolean, version: Int = VERSION): Boolean = version in setOf(VERSION, PROFILE_VERSION, PROFILE_DIAGNOSTIC_VERSION) && peer != null && peer.state == "paired" &&
        peer.own_device && peer.remote_own_device && peer.contacts_read_enabled && permission &&
        peer.device_status_granted && peer.remote_device_status_granted && peer.remote_device_status_available &&
        version in peer.remote_device_status_versions

    fun validUid(value: String): Boolean = value.isNotEmpty() && value.codePointCount(0, value.length) <= 256 &&
        value.none(Char::isISOControl)

    fun validateRequest(value: JsonObject): List<String> {
        require(value.keys == setOf("version", "request_id", "action", "offset", "uids"))
        require(value.long("version") in setOf(VERSION.toLong(), PROFILE_VERSION.toLong(), PROFILE_DIAGNOSTIC_VERSION.toLong()) && uuid4.matches(value.string("request_id")))
        val action = value.string("action")
        val offset = value.long("offset")
        val uids = (value["uids"] as? JsonArray ?: error("invalid_contact_batch")).map {
            (it as? JsonPrimitive)?.takeIf { node -> node.isString }?.content ?: error("invalid_contact_uid")
        }
        require(uids.all(::validUid) && uids.distinct().size == uids.size)
        if (value.long("version") in setOf(PROFILE_VERSION.toLong(), PROFILE_DIAGNOSTIC_VERSION.toLong())) { require(action == "profile" && offset == 0L && uids.isEmpty()); return uids }
        require((action == "index" && offset in 0L..MAX_CONTACTS.toLong() && uids.isEmpty()) ||
            (action == "cards" && offset == 0L && uids.size in 1..5))
        return uids
    }

    fun report(request: JsonObject, total: Int, contacts: List<JsonObject>): JsonObject {
        validateRequest(request)
        return buildJsonObject {
            put("version", JsonPrimitive(VERSION)); put("request_id", request.getValue("request_id"))
            put("action", request.getValue("action")); put("offset", request.getValue("offset"))
            put("total", JsonPrimitive(total)); put("contacts", JsonArray(contacts))
        }.also(::validateReport)
    }

    fun validateReport(value: JsonObject) {
        if (value["version"] in setOf(JsonPrimitive(PROFILE_VERSION), JsonPrimitive(PROFILE_DIAGNOSTIC_VERSION))) {
            val diagnostic = value["version"] == JsonPrimitive(PROFILE_DIAGNOSTIC_VERSION)
            require(value.keys == setOf("version", "request_id", "action", "offset", "total", "contacts", "profile") + if (diagnostic) setOf("diagnostics") else emptySet())
            if (diagnostic) {
                val entries = value["diagnostics"] as? JsonArray ?: error("invalid_profile_diagnostics")
                require(entries.size <= 32)
                for (node in entries) {
                    val entry = node as? JsonObject ?: error("invalid_profile_diagnostics")
                    require(entry.keys == setOf("stage", "rows", "outcome") && entry.string("stage") in diagnosticStages &&
                        entry.string("outcome") in diagnosticOutcomes && entry.long("rows") in -1L..1000L)
                }
            }
            require(uuid4.matches(value.string("request_id")) && value.string("action") == "profile" && value.long("offset") == 0L &&
                (value["contacts"] as JsonArray).isEmpty())
            val profile = value["profile"] as JsonObject
            require(profile.keys == setOf("state", "vcard") && profile.string("state") in setOf("available", "unavailable"))
            val card = profile.string("vcard")
            require(value.long("total") == if (profile.string("state") == "available") 1L else 0L)
            require(if (profile.string("state") == "available") card.startsWith("BEGIN:VCARD\r\n") && card.endsWith("END:VCARD\r\n") &&
                card.toByteArray().size <= MAX_CARD_BYTES else card.isEmpty())
            require(TelefonKanonisch.bytes(value).size <= MAX_REPORT_BYTES); return
        }
        require(value.keys == setOf("version", "request_id", "action", "offset", "total", "contacts"))
        require(value.long("version") == VERSION.toLong() && uuid4.matches(value.string("request_id")))
        val action = value.string("action")
        val offset = value.long("offset"); val total = value.long("total")
        val contacts = value["contacts"] as? JsonArray ?: error("invalid_contact_batch")
        require(total in 0L..MAX_CONTACTS.toLong() && offset in 0L..total)
        require((action == "index" && contacts.size <= PAGE_SIZE && offset + contacts.size <= total &&
            (contacts.isNotEmpty() || offset == total)) ||
            (action == "cards" && offset == 0L && contacts.size in 1..5 && total == contacts.size.toLong()))
        val seen = mutableSetOf<String>()
        contacts.forEach { node ->
            val item = node as? JsonObject ?: error("invalid_contact_batch")
            require(item.keys == if (action == "index") setOf("uid", "timestamp") else setOf("uid", "timestamp", "vcard"))
            require(validUid(item.string("uid")) && seen.add(item.string("uid")))
            require(item.long("timestamp") in 0L..253402300799999L)
            if (action == "cards") {
                val card = item.string("vcard")
                require(card.startsWith("BEGIN:VCARD\r\n") && card.endsWith("END:VCARD\r\n") &&
                    card.toByteArray(Charsets.UTF_8).size <= MAX_CARD_BYTES)
            }
        }
        require(TelefonKanonisch.bytes(value).size <= MAX_REPORT_BYTES)
    }
    fun profileReport(request: JsonObject, card: String, diagnostics: List<JsonObject> = emptyList()): JsonObject = buildJsonObject {
        put("version", request.getValue("version")); put("request_id", request.getValue("request_id")); put("action", "profile"); put("offset", 0)
        put("total", if (card.isEmpty()) 0 else 1); put("contacts", JsonArray(emptyList()))
        put("profile", buildJsonObject { put("state", if (card.isEmpty()) "unavailable" else "available"); put("vcard", card) })
        if (request["version"] == JsonPrimitive(PROFILE_DIAGNOSTIC_VERSION)) put("diagnostics", JsonArray(diagnostics))
    }.also(::validateReport)
}
