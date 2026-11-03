package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.util.Locale

/** Explicit metadata/configuration/run requests only. No paths, OS permission
 * claims, file grants or album READ authority can be supplied in this body.
 */
internal class DeviceFileSourceCommand private constructor(val requestId: String, val operation: String,
    val expectedVersion: String?, val enabled: Boolean?, val kinds: Set<GallerySourceKind>, val expires: Long,
    val catalogId: String? = null, val after: Int = 0,
    val albumId: String? = null, val desktopChoice: Boolean? = null, val runId: String? = null,
    val originalJobId: String? = null, val originalJobVersion: String? = null,
    val lookupSourceId: String? = null, val lookupTransferId: String? = null, val lookupManifestSha256: String? = null) {
    companion object {
        const val REQUEST = "file_transfer.sources.request"
        const val RESULT = "file_transfer.sources.result"
        const val CATALOG = "file_transfer.sources.catalog"
        const val PERMISSION_RESULT = "file_transfer.sources.permission_result"
        const val RUN_RESULT = "file_transfer.sources.run_result"
        const val MEDIA = "file_transfer.sources.media"
        const val RESUME = "file_transfer.sources.resume"
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
            if (operation == "resume_lookup") {
                if (body.keys != base + setOf("expected_version", "source_id", "transfer_id", "manifest_sha256")) fail()
                fun id(name: String) = text(name).takeIf { Regex("[0-9a-f]{32}").matches(it) } ?: fail()
                val version = text("expected_version").takeIf(DeviceFileControl::hash) ?: fail()
                val manifest = text("manifest_sha256").takeIf(DeviceFileControl::hash) ?: fail()
                return DeviceFileSourceCommand(message.string("message_id"), operation, version, null, emptySet(), message.long("expires_ms"),
                    lookupSourceId = id("source_id"), lookupTransferId = id("transfer_id"), lookupManifestSha256 = manifest)
            }
            if (operation in setOf("resume_run", "resume_status", "cancel_resume", "offer_resume")) {
                val starting = operation == "resume_run"
                if (body.keys != base + setOf("expected_version") + (if (starting)
                    setOf("catalog_id", "album_id", "desktop_choice", "original_job_id", "original_job_version") else setOf("run_id"))) fail()
                val version = text("expected_version").takeIf(DeviceFileControl::hash) ?: fail()
                if (!starting) return DeviceFileSourceCommand(message.string("message_id"), operation, version, null, emptySet(),
                    message.long("expires_ms"), runId = opaque("run_id"))
                val choice = (body["desktop_choice"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: fail()
                val jobId = text("original_job_id").takeIf { Regex("[0-9a-f]{32}").matches(it) } ?: fail()
                val jobVersion = text("original_job_version").takeIf(DeviceFileControl::hash) ?: fail()
                return DeviceFileSourceCommand(message.string("message_id"), operation, version, null, emptySet(), message.long("expires_ms"),
                    catalogId = opaque("catalog_id"), albumId = opaque("album_id"), desktopChoice = choice,
                    originalJobId = jobId, originalJobVersion = jobVersion)
            }
            if (operation == "media_page") {
                if (body.keys != base + setOf("expected_version", "run_id", "after")) fail()
                val version = text("expected_version").takeIf(DeviceFileControl::hash) ?: fail()
                val after = (body["after"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toIntOrNull()
                    ?.takeIf { it in 0..DeviceFileManifest.MAX_FILES } ?: fail()
                return DeviceFileSourceCommand(message.string("message_id"), operation, version, null, emptySet(),
                    message.long("expires_ms"), after = after, runId = opaque("run_id"))
            }
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
