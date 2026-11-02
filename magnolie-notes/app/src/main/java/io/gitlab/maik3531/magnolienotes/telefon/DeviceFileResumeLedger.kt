package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest
import java.util.Locale

data class DeviceTransferBinding(val senderId: String, val receiverId: String,
    val senderIdentitySha256: String, val receiverIdentitySha256: String,
    val permissionEpoch: String, val destinationToken: String) {
    init {
        val identity = Regex("[A-Za-z0-9_-]{16,160}"); val hash = Regex("[0-9a-f]{64}")
        if (!identity.matches(senderId) || !identity.matches(receiverId) ||
            listOf(senderIdentitySha256, receiverIdentitySha256, permissionEpoch, destinationToken).any { !hash.matches(it) })
            throw TelefonProtokollFehler("Invalid native file transfer binding.")
    }
    fun snapshot() = JsonObject(mapOf("sender_id" to JsonPrimitive(senderId), "receiver_id" to JsonPrimitive(receiverId),
        "sender_identity_sha256" to JsonPrimitive(senderIdentitySha256), "receiver_identity_sha256" to JsonPrimitive(receiverIdentitySha256),
        "permission_epoch" to JsonPrimitive(permissionEpoch), "destination_token" to JsonPrimitive(destinationToken)))
}

/** Native staging proofs only; no SAF access, grant defaults, network ACK or final publication. */
class DeviceFileResumeLedger(val manifest: DeviceFileManifest, val binding: DeviceTransferBinding,
    private val currentBinding: () -> DeviceTransferBinding?) {
    private val proofs = mutableMapOf<Pair<String, Int>, String>()
    init {
        if (manifest.senderId != binding.senderId || manifest.receiverId != binding.receiverId) fail()
        fresh()
    }
    private fun fresh() { if (currentBinding() != binding) fail() }
    private fun member(fileId: String) = manifest.files.singleOrNull { it.id == fileId } ?: fail()
    private fun chunk(fileId: String, index: Int): Triple<DeviceManifestFile, Long, Int> {
        fresh(); val file = member(fileId)
        if (index !in 0 until chunks(file)) fail()
        val offset = index.toLong() * DeviceFileManifest.CHUNK_BYTES
        return Triple(file, offset, minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), file.size - offset).toInt())
    }

    val verifiedBytes: Long get() = synchronized(this) {
        fresh(); proofs.keys.sumOf { chunk(it.first, it.second).third.toLong() }
    }

    @Synchronized fun missing(fileId: String): List<Int> {
        fresh(); return (0 until chunks(member(fileId))).filter { (fileId to it) !in proofs }
    }

    @Synchronized fun record(fileId: String, index: Int, data: ByteArray,
        writeExact: (String, Long, ByteArray) -> Unit, readChunk: (String, Long, Int) -> ByteArray) {
        val (_, offset, size) = chunk(fileId, index)
        if (data.size != size) fail()
        val bytes = data.copyOf(); val witness = hash(bytes); val key = fileId to index
        val previous = proofs[key]
        if (previous != null) { if (previous != witness) fail() }
        else writeExact(fileId, offset, bytes)
        fresh()
        val actual = readChunk(fileId, offset, size)
        if (actual.size != size || hash(actual) != witness) fail()
        fresh(); proofs[key] = witness
    }

    @Synchronized fun checkpoint(): JsonObject {
        fresh()
        return JsonObject(mapOf("format" to JsonPrimitive(1), "manifest_sha256" to JsonPrimitive(manifest.fingerprint),
            "binding" to binding.snapshot(), "chunks" to JsonArray(proofs.entries
                .sortedWith(compareBy({ it.key.first }, { it.key.second })).map { (key, sha) ->
                    JsonObject(mapOf("file_id" to JsonPrimitive(key.first), "index" to JsonPrimitive(key.second), "sha256" to JsonPrimitive(sha))) })))
    }

    @Synchronized fun verifiedFile(fileId: String, readChunk: (String, Long, Int) -> ByteArray): DeviceManifestFile {
        if (missing(fileId).isNotEmpty()) fail()
        val file = member(fileId); val digest = MessageDigest.getInstance("SHA-256")
        for (index in 0 until chunks(file)) {
            val (_, offset, size) = chunk(fileId, index)
            val actual = readChunk(fileId, offset, size)
            if (actual.size != size || hash(actual) != proofs[fileId to index]) fail()
            digest.update(actual); fresh()
        }
        if (readChunk(fileId, file.size, 1).isNotEmpty() || hex(digest.digest()) != file.sha256) fail()
        fresh(); return file
    }

    companion object {
        private fun fail(): Nothing = throw TelefonProtokollFehler("File transfer binding, chunk or readback changed.")
        private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        private fun hash(bytes: ByteArray) = hex(MessageDigest.getInstance("SHA-256").digest(bytes))
        private fun chunks(file: DeviceManifestFile) = ((file.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
        private fun exact(value: JsonObject, fields: Set<String>) { if (value.keys != fields) fail() }
        private fun text(value: JsonObject, name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        private fun integer(value: JsonObject, name: String): Long = (value[name] as? JsonPrimitive)
            ?.takeIf { !it.isString && Regex("0|[1-9][0-9]*").matches(it.content) }?.content?.toLongOrNull() ?: fail()

        /** Checkpoint decoding must retain the existing strict duplicate-key/frame boundary. */
        fun restore(manifest: DeviceFileManifest, binding: DeviceTransferBinding, currentBinding: () -> DeviceTransferBinding?,
            checkpoint: JsonObject, readChunk: (String, Long, Int) -> ByteArray): DeviceFileResumeLedger {
            exact(checkpoint, setOf("format", "manifest_sha256", "binding", "chunks"))
            if (integer(checkpoint, "format") != 1L || text(checkpoint, "manifest_sha256") != manifest.fingerprint ||
                checkpoint["binding"] != binding.snapshot()) fail()
            val claims = checkpoint["chunks"] as? JsonArray ?: fail()
            if (claims.size > manifest.files.sumOf { chunks(it) }) fail()
            val result = DeviceFileResumeLedger(manifest, binding, currentBinding)
            for (entry in claims) {
                val proof = entry as? JsonObject ?: fail()
                exact(proof, setOf("file_id", "index", "sha256"))
                val id = text(proof, "file_id"); val rawIndex = integer(proof, "index"); val witness = text(proof, "sha256")
                if (rawIndex > Int.MAX_VALUE || !Regex("[0-9a-f]{64}").matches(witness)) fail()
                val index = rawIndex.toInt(); val (_, offset, size) = result.chunk(id, index); val key = id to index
                if (key in result.proofs) fail()
                val actual = readChunk(id, offset, size)
                if (actual.size != size || hash(actual) != witness) fail()
                result.fresh(); result.proofs[key] = witness
            }
            return result
        }
    }
}
