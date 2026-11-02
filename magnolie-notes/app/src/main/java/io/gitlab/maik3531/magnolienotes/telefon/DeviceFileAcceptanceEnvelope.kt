package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

internal data class DeviceFileRemoteAcceptance internal constructor(val offerId: String, val manifestSha256: String,
    val transferId: String, val acceptanceSha256: String, val permissionEpoch: String, val destinationToken: String,
    val expires: Long, val commandDigest: String)

/** Remote native receiver metadata, never phone READ or a saved receipt. The
 * sender independently checks its actual source, offer output and live consent.
 * No destination path or partial manifest can be supplied here.
 */
internal object DeviceFileAcceptanceEnvelope {
    const val KIND = "file_transfer.accept"
    fun parse(message: JsonObject, now: Long = System.currentTimeMillis()): DeviceFileRemoteAcceptance {
        fun fail(): Nothing = DeviceFileControl.fail("file_accept_invalid_envelope")
        if (TelefonKanonisch.bytes(message).size > DeviceFileControl.MAX_WIRE_BYTES) fail()
        TelefonNachrichten.validateHeader(message, now)
        if (message.string("kind") != KIND || now >= message.long("expires_ms") ||
            message.long("expires_ms") - message.long("created_ms") > DeviceFileControl.MAX_TTL_MS) fail()
        val body = message["body"] as? JsonObject ?: fail()
        if (body.keys != setOf("format", "offer_id", "manifest_sha256", "transfer_id", "acceptance_sha256", "permission_epoch", "destination_token") ||
            body["format"] != JsonPrimitive(1)) fail()
        fun text(name: String) = (body[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        fun hash(name: String) = text(name).takeIf(DeviceFileControl::hash) ?: fail()
        val offer = text("offer_id").takeIf {
            Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(it)
        } ?: fail()
        val transfer = text("transfer_id").takeIf { Regex("[0-9a-f]{32}").matches(it) } ?: fail()
        return DeviceFileRemoteAcceptance(offer, hash("manifest_sha256"), transfer, hash("acceptance_sha256"),
            hash("permission_epoch"), hash("destination_token"), message.long("expires_ms"),
            DeviceFileControl.digest("magnolie-file-acceptance-command-v1\u0000", message))
    }
}
