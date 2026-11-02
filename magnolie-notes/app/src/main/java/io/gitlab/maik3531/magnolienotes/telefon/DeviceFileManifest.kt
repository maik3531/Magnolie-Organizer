package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.text.Normalizer
import java.util.Collections
import java.util.Locale

data class DeviceManifestFile(val id: String, val path: String, val size: Long, val sha256: String)

/** Immutable general-file metadata only. No photo grant, SAF access, listener or book ACK. */
class DeviceFileManifest private constructor(
    val transferId: String, val sourceId: String, val senderId: String, val receiverId: String,
    entries: List<DeviceManifestFile>, val totalBytes: Long
) {
    val files: List<DeviceManifestFile> = Collections.unmodifiableList(entries.toList())
    val fingerprint: String = run {
        val hash = MessageDigest.getInstance("SHA-256")
        hash.update("magnolie-file-manifest-v1\u0000".toByteArray(Charsets.US_ASCII))
        fun integer(value: Int) { hash.update(ByteBuffer.allocate(4).putInt(value).array()) }
        fun long(value: Long) { hash.update(ByteBuffer.allocate(8).putLong(value).array()) }
        fun text(value: String) { val bytes = value.toByteArray(Charsets.UTF_8); integer(bytes.size); hash.update(bytes) }
        listOf(transferId, sourceId, senderId, receiverId).forEach(::text)
        integer(CHUNK_BYTES); integer(files.size); long(totalBytes)
        files.forEach { file ->
            text(file.id); text(file.path); long(file.size)
            hash.update(file.sha256.chunked(2).map { it.toInt(16).toByte() }.toByteArray())
        }
        hash.digest().joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    }

    fun wire(): JsonObject = JsonObject(mapOf(
        "format" to JsonPrimitive(1), "transfer_id" to JsonPrimitive(transferId), "source_id" to JsonPrimitive(sourceId),
        "sender_id" to JsonPrimitive(senderId), "receiver_id" to JsonPrimitive(receiverId),
        "chunk_bytes" to JsonPrimitive(CHUNK_BYTES), "total_bytes" to JsonPrimitive(totalBytes),
        "files" to JsonArray(files.map { file -> JsonObject(mapOf("id" to JsonPrimitive(file.id),
            "path" to JsonPrimitive(file.path), "size" to JsonPrimitive(file.size), "sha256" to JsonPrimitive(file.sha256))) })
    ))

    companion object {
        const val CHUNK_BYTES = 65536
        const val MAX_FILES = 128
        const val MAX_FILE_BYTES = 50L * 1024 * 1024
        const val MAX_TOTAL_BYTES = 400L * 1024 * 1024
        private val id = Regex("[0-9a-f]{32}")
        private val sha = Regex("[0-9a-f]{64}")
        private val device = Regex("[A-Za-z0-9_-]{16,160}")
        private val integer = Regex("0|[1-9][0-9]*")
        private val reserved = setOf("CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$") +
            listOf("COM", "LPT").flatMap { prefix -> "123456789¹²³".map { prefix + it } }
        private fun fail(): Nothing = throw TelefonProtokollFehler("Invalid immutable device file manifest.")
        private fun exact(value: JsonObject, fields: Set<String>) { if (value.keys != fields) fail() }
        private fun text(value: JsonObject, name: String): String =
            (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        private fun number(value: JsonObject, name: String): Long =
            (value[name] as? JsonPrimitive)?.takeIf { !it.isString && integer.matches(it.content) }
                ?.content?.toLongOrNull() ?: fail()

        internal fun portablePath(value: String): Boolean {
            val parts = value.split('/')
            if (value.isEmpty() || value.codePointCount(0, value.length) > 1024 ||
                !Normalizer.isNormalized(value, Normalizer.Form.NFC) || value.toByteArray(Charsets.UTF_8).size > 4096 ||
                parts.size > 16) return false
            return parts.all { part ->
                part.isNotEmpty() && part !in setOf(".", "..") && part.length <= 255 &&
                    !part.endsWith('.') && !part.endsWith(' ') && part.none { it in "<>:\"\\|?*" } &&
                    part.substringBefore('.').trimEnd(' ').uppercase(Locale.ROOT) !in reserved &&
                    part.codePoints().toArray().none { Character.getType(it) in setOf(
                        Character.CONTROL.toInt(), Character.FORMAT.toInt(), Character.SURROGATE.toInt(),
                        Character.PRIVATE_USE.toInt(), Character.UNASSIGNED.toInt()) }
            }
        }

        /** Called only after TelefonRahmen's strict duplicate-key/bounded frame decoding. */
        fun parse(value: JsonObject): DeviceFileManifest {
            exact(value, setOf("format", "transfer_id", "source_id", "sender_id", "receiver_id", "chunk_bytes", "total_bytes", "files"))
            if (number(value, "format") != 1L || number(value, "chunk_bytes") != CHUNK_BYTES.toLong()) fail()
            val transfer = text(value, "transfer_id"); val source = text(value, "source_id")
            val sender = text(value, "sender_id"); val receiver = text(value, "receiver_id")
            if (!id.matches(transfer) || !id.matches(source) || !device.matches(sender) || !device.matches(receiver) || sender == receiver) fail()
            val raw = value["files"] as? JsonArray ?: fail()
            if (raw.size !in 1..MAX_FILES) fail()
            val files = raw.map { entry ->
                val file = entry as? JsonObject ?: fail()
                exact(file, setOf("id", "path", "size", "sha256"))
                DeviceManifestFile(text(file, "id"), text(file, "path"), number(file, "size"), text(file, "sha256")).also {
                    if (!id.matches(it.id) || !sha.matches(it.sha256) || !portablePath(it.path) || it.size !in 0..MAX_FILE_BYTES) fail()
                }
            }
            if (files.map { it.id }.distinct().size != files.size) fail()
            // Conservative receiver preflight; native destination planning still
            // checks its actual filesystem. The second expansion also handles
            // capital sharp-S, which a single uppercase pass leaves unchanged.
            val paths = files.map { Normalizer.normalize(it.path.uppercase(Locale.ROOT)
                .lowercase(Locale.ROOT).uppercase(Locale.ROOT), Normalizer.Form.NFC) }
            if (paths.distinct().size != paths.size) fail()
            val pathSet = paths.toSet()
            paths.forEach { item ->
                val parts = item.split('/')
                if ((1 until parts.size).any { parts.take(it).joinToString("/") in pathSet }) fail()
            }
            val total = number(value, "total_bytes")
            if (total !in 0..MAX_TOTAL_BYTES || total != files.sumOf { it.size }) fail()
            return DeviceFileManifest(transfer, source, sender, receiver, files, total)
        }
    }
}
