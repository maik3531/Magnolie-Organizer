package io.gitlab.maik3531.magnolienotes.telefon

import java.time.ZoneId
import java.util.UUID
import kotlinx.serialization.json.*

/** Installation clock metadata only; no GPS coordinates or location permission. */
object PhoneTimeZone {
    const val VERSION = 12
    private fun uuid(value: String) = runCatching {
        val parsed = UUID.fromString(value)
        parsed.version() == 4 && parsed.toString() == value
    }.getOrDefault(false)
    private fun number(body: JsonObject, name: String): Long {
        val value = body[name] as? JsonPrimitive ?: error("invalid_time_zone_status")
        require(!value.isString)
        return value.longOrNull ?: error("invalid_time_zone_status")
    }

    fun zoneId(value: String): String? {
        val zone = when (value) { "Z", "GMT", "Etc/UTC", "Etc/GMT" -> "UTC"; else -> value }
        if (zone.length > 128 || ".." in zone || zone != "UTC" && !Regex("[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+").matches(zone)) return null
        return runCatching { ZoneId.of(zone); zone }.getOrNull()
    }

    fun validateRequest(body: JsonObject) {
        require(body.keys == setOf("version", "request_id") && number(body, "version") == VERSION.toLong() && uuid(body.string("request_id")))
    }

    fun report(requestId: String, zone: String = ZoneId.systemDefault().id, now: Long = System.currentTimeMillis()): JsonObject {
        require(uuid(requestId) && now in 0..253402300799999L)
        val known = zoneId(zone)
        return buildJsonObject {
            put("version", JsonPrimitive(VERSION)); put("request_id", JsonPrimitive(requestId))
            put("state", JsonPrimitive(if (known == null) "unavailable" else "available"))
            put("time_zone", JsonPrimitive(known.orEmpty())); put("captured_ms", JsonPrimitive(now))
        }
    }

    fun validateReport(body: JsonObject) {
        require(body.keys == setOf("version", "request_id", "state", "time_zone", "captured_ms"))
        require(number(body, "version") == VERSION.toLong() && uuid(body.string("request_id")) && number(body, "captured_ms") in 0..253402300799999L)
        require(when (body.string("state")) {
            "available" -> zoneId(body.string("time_zone")) != null
            "unavailable" -> body.string("time_zone").isEmpty()
            else -> false
        })
    }

    fun allowed(peer: TelefonPeer) = peer.state == "paired" && peer.own_device && peer.remote_own_device && peer.device_status_granted &&
        peer.remote_device_status_granted && peer.remote_device_status_available && VERSION in peer.remote_device_status_versions
}
