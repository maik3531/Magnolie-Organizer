package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.util.Locale

/** Metadata/configuration only. No paths, OS permission claims, file grants,
 * run scheduling or album READ authority can be supplied in this body.
 */
internal class DeviceFileSourceCommand private constructor(val requestId: String, val operation: String,
    val expectedVersion: String?, val enabled: Boolean?, val kinds: Set<GallerySourceKind>, val expires: Long,
    val catalogId: String? = null, val after: Int = 0,
    val albumId: String? = null, val desktopChoice: Boolean? = null, val runId: String? = null) {
    companion object {
        const val REQUEST = "file_transfer.sources.request"
        const val RESULT = "file_transfer.sources.result"
        const val CATALOG = "file_transfer.sources.catalog"
        const val PERMISSION_RESULT = "file_transfer.sources.permission_result"
        const val RUN_RESULT = "file_transfer.sources.run_result"
        fun parse(message: JsonObject, now: Long = System.currentTimeMillis()): DeviceFileSourceCommand {
            fun fail(): Nothing = DeviceFileControl.fail("file_sources_invalid_command")
            if (TelefonKanonisch.bytes(message).size > DeviceFileControl.MAX_WIRE_BYTES) fail()
            TelefonNachrichten.validateHeader(message, now)
            if (message.string("kind") != REQUEST || now >= message.long("expires_ms") ||
                message.long("expires_ms") - message.long("created_ms") > DeviceFileControl.MAX_TTL_MS) fail()
            val body = message["body"] as? JsonObject ?: fail()
            fun text(name: String) = (body[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            val operation = text("operation")
            val base = setOf("format", "operation")
            if (body["format"] != JsonPrimitive(1)) fail()
            fun opaque(name: String) = text(name).takeIf {
                Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(it)
            } ?: fail()
            if (operation in setOf("run", "run_status", "cancel_run", "offer_run")) {
                if (body.keys != base + setOf("expected_version") +
                    (if (operation == "run") setOf("catalog_id", "album_id", "desktop_choice") else setOf("run_id"))) fail()
                val version = text("expected_version").takeIf(DeviceFileControl::hash) ?: fail()
                if (operation == "run") {
                    val choice = (body["desktop_choice"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: fail()
                    return DeviceFileSourceCommand(message.string("message_id"), operation, version, null, emptySet(),
                        message.long("expires_ms"), catalogId = opaque("catalog_id"), albumId = opaque("album_id"), desktopChoice = choice)
                }
                return DeviceFileSourceCommand(message.string("message_id"), operation, version, null, emptySet(),
                    message.long("expires_ms"), runId = opaque("run_id"))
            }
            if (operation == "status") {
                if (body.keys != base) fail()
                return DeviceFileSourceCommand(message.string("message_id"), operation, null, null, emptySet(), message.long("expires_ms"))
            }
            if (operation in setOf("discover", "catalog_page", "request_read")) {
                if (body.keys != base + setOf("expected_version") + (if (operation == "catalog_page") setOf("catalog_id", "after") else emptySet())) fail()
                val expected = text("expected_version").takeIf(DeviceFileControl::hash) ?: fail()
                val id = if (operation == "catalog_page") text("catalog_id").takeIf {
                    Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(it)
                } ?: fail() else null
                val after = if (operation == "catalog_page") (body["after"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toIntOrNull()
                    ?.takeIf { it in 0..AndroidGalleryAlbumDiscovery.MAX_ALBUMS } ?: fail() else 0
                return DeviceFileSourceCommand(message.string("message_id"), operation, expected, null, emptySet(), message.long("expires_ms"), id, after)
            }
            if (operation != "configure" || body.keys != base + setOf("expected_version", "enabled", "kinds")) fail()
            val expected = text("expected_version").takeIf(DeviceFileControl::hash) ?: fail()
            val enabled = (body["enabled"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: fail()
            val raw = body["kinds"] as? JsonArray ?: fail()
            if (raw.size > GallerySourceKind.entries.size) fail()
            val labels = raw.map { (it as? JsonPrimitive)?.takeIf { value -> value.isString }?.content ?: fail() }
            if (labels != labels.sorted().distinct()) fail()
            val kinds = labels.map { label -> GallerySourceKind.entries.singleOrNull { it.name.lowercase(Locale.ROOT) == label } ?: fail() }.toSet()
            if (enabled && kinds.isEmpty()) fail()
            return DeviceFileSourceCommand(message.string("message_id"), operation, expected, enabled, kinds, message.long("expires_ms"))
        }
    }
}
