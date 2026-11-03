package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest
import java.util.Locale

/** Authenticated historical identity fields, never a reconstructed native lease. */
internal class NativePhotoSourceContext private constructor(val record: JsonObject) {
    val receiverId: String get() = (record["receiver"] as JsonPrimitive).content
    val receiverIdentitySha256: String get() = (record["identity"] as JsonPrimitive).content
    val permissionEpoch: String get() = (record["permission_epoch"] as JsonPrimitive).content
    val pairingEpoch: String? get() = (record["pairing_epoch"] as? JsonPrimitive)?.content
    companion object {
        fun wire(lease: NativePhotoSourceLease) = JsonObject(mapOf(
            "tree" to JsonPrimitive(lease.sourceKey), "version" to JsonPrimitive(lease.version),
            "epoch" to JsonPrimitive(lease.sourceEpoch), "receiver" to JsonPrimitive(lease.receiver.peerId),
            "identity" to JsonPrimitive(lease.receiver.identitySha256), "permission_epoch" to JsonPrimitive(lease.receiver.permissionEpoch),
            "read_grant" to JsonPrimitive(lease.readGrantToken)) +
            (lease.receiver.pairingEpoch?.let { mapOf("pairing_epoch" to JsonPrimitive(it)) } ?: emptyMap()))

        fun parse(record: JsonObject, originalHash: String): NativePhotoSourceContext {
            fun fail(): Nothing = DeviceFileControl.fail("photo_jobs_source_context_witness_invalid")
            val keys = setOf("tree", "version", "epoch", "receiver", "identity", "permission_epoch", "read_grant")
            if (record.keys != keys && record.keys != keys + "pairing_epoch") fail()
            fun text(name: String) = (record[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            for (name in listOf("tree", "read_grant")) {
                val value = text(name)
                if (value.length !in 1..4096 || value.any { it.code < 32 || it.code == 127 }) fail()
            }
            if (!Regex("[A-Za-z0-9_-]{16,160}").matches(text("receiver"))) fail()
            for (name in listOf("version", "epoch", "identity", "permission_epoch") + if ("pairing_epoch" in record) listOf("pairing_epoch") else emptyList())
                if (!DeviceFileControl.hash(text(name))) fail()
            val actual = MessageDigest.getInstance("SHA-256").digest(TelefonKanonisch.bytes(record))
                .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
            if (!DeviceFileControl.hash(originalHash) || actual != originalHash) fail()
            return NativePhotoSourceContext(record)
        }
    }
}
