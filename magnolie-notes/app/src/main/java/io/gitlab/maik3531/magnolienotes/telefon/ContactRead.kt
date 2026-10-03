package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/** Optional, explicitly authorized read-only device-status resource, version 5. */
object ContactRead {
    const val VERSION = 5
    const val PAGE_SIZE = 128
    const val MAX_CONTACTS = 10_000
    const val MAX_CARD_BYTES = 96 * 1024
    const val MAX_REPORT_BYTES = 128 * 1024
    private val uuid4 = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

    fun allowed(peer: TelefonPeer?, permission: Boolean): Boolean = peer != null && peer.state == "paired" &&
        peer.own_device && peer.remote_own_device && peer.contacts_read_enabled && permission &&
        peer.device_status_granted && peer.remote_device_status_granted && peer.remote_device_status_available &&
        VERSION in peer.remote_device_status_versions

    fun validUid(value: String): Boolean = value.isNotEmpty() && value.codePointCount(0, value.length) <= 256 &&
        value.none(Char::isISOControl)

    fun validateRequest(value: JsonObject): List<String> {
        require(value.keys == setOf("version", "request_id", "action", "offset", "uids"))
        require(value.long("version") == VERSION.toLong() && uuid4.matches(value.string("request_id")))
        val action = value.string("action")
        val offset = value.long("offset")
        val uids = (value["uids"] as? JsonArray ?: error("invalid_contact_batch")).map {
            (it as? JsonPrimitive)?.takeIf { node -> node.isString }?.content ?: error("invalid_contact_uid")
        }
        require(uids.all(::validUid) && uids.distinct().size == uids.size)
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
}
