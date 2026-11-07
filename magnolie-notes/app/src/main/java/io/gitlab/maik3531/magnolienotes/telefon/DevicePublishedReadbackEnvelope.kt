package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Parsed peer metadata only; never Saved, write authority or Chunk permission. */
internal class RemotePublishedReadback internal constructor(val body: JsonObject) {
    val grantsWriteAuthority: Boolean get() = false
    val isSavedReceipt: Boolean get() = false
    val allowsChunkOutput: Boolean get() = false
}

internal object DevicePublishedReadbackEnvelope {
    const val KIND = "file_transfer.published.readback"
    private const val DESTINATION = "magnolie-published-readback-destination-v1\u0000"
    private const val BINDING = "magnolie-published-readback-binding-v1\u0000"
    private const val READBACK = "magnolie-published-readback-v1\u0000"
    private val fields = setOf("format", "offer_id", "manifest_sha256", "transfer_id", "source_id", "file_id", "size", "sha256",
        "media_type", "mime_type", "publication_sha256", "row_sha256", "permission_epoch", "readback_nonce")
    private fun validateContext(value: JsonObject): JsonObject {
        if (value.keys != fields || value["format"] != JsonPrimitive(1)) fail()
        fun text(name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        for (name in listOf("manifest_sha256", "sha256", "publication_sha256", "row_sha256", "permission_epoch", "readback_nonce"))
            if (!DeviceFileControl.hash(text(name))) fail()
        for (name in listOf("transfer_id", "source_id", "file_id")) if (!Regex("[0-9a-f]{32}").matches(text(name))) fail()
        if (!Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(text("offer_id"))) fail()
        val size = (value["size"] as? JsonPrimitive)?.takeIf { !it.isString && Regex("[1-9][0-9]*").matches(it.content) }?.content?.toLongOrNull() ?: fail()
        if (size !in 1..DeviceFileManifest.MAX_FILE_BYTES || text("media_type") !in setOf("images", "video") ||
            !Regex((if (text("media_type") == "images") "image/" else "video/") + "[a-z0-9.+-]{1,80}").matches(text("mime_type"))) fail()
        return value
    }
    fun destinationToken(context: JsonObject) = DeviceFileControl.digest(DESTINATION, validateContext(context))
    /** Pure codec only; encoding a body does not establish native provider IO. */
    fun encodeBody(context: JsonObject, binding: DeviceTransferBinding): JsonObject {
        validateContext(context)
        if (binding.permissionEpoch != context.string("permission_epoch") || binding.destinationToken != destinationToken(context)) fail()
        val value = JsonObject(context + mapOf("destination_token" to JsonPrimitive(binding.destinationToken),
            "binding_sha256" to JsonPrimitive(DeviceFileControl.digest(BINDING, binding.snapshot()))))
        return JsonObject(value + ("readback_sha256" to JsonPrimitive(DeviceFileControl.digest(READBACK, value))))
    }
    fun parse(message: JsonObject, offer: JsonObject, binding: DeviceTransferBinding, kind: GalleryMediaType,
        now: Long = System.currentTimeMillis()): RemotePublishedReadback {
        if (TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX) fail()
        TelefonNachrichten.validateHeader(message, now)
        if (message.string("kind") != KIND || now >= message.long("expires_ms") ||
            message.long("expires_ms") - message.long("created_ms") > DeviceFileControl.MAX_TTL_MS) fail()
        val body = message["body"] as? JsonObject ?: fail()
        if (body.keys != fields + setOf("destination_token", "binding_sha256", "readback_sha256")) fail()
        if (encodeBody(JsonObject(body.filterKeys { it in fields }), binding) != body) fail()
        val manifest = DeviceFileOfferEnvelope.validate(offer, binding.senderId, binding.receiverId, now)
        if (now < offer.long("created_ms") || now >= offer.long("expires_ms")) fail()
        val file = manifest.files.singleOrNull() ?: fail()
        if (message.long("created_ms") < offer.long("created_ms") || message.long("expires_ms") > offer.long("expires_ms") ||
            body["offer_id"] != offer["message_id"] || body["manifest_sha256"] != JsonPrimitive(manifest.fingerprint) ||
            body["transfer_id"] != JsonPrimitive(manifest.transferId) || body["source_id"] != JsonPrimitive(manifest.sourceId) ||
            body["file_id"] != JsonPrimitive(file.id) || body["size"] != JsonPrimitive(file.size) || body["sha256"] != JsonPrimitive(file.sha256) ||
            body["media_type"] != JsonPrimitive(kind.uriSegment)) fail()
        return RemotePublishedReadback(body)
    }
    private fun fail(): Nothing = DeviceFileControl.fail("file_published_readback_invalid")
}
