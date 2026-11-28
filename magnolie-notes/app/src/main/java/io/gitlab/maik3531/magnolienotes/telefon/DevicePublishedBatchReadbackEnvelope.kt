package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Whole-offer peer metadata only; not the v1 type used by single-file retirement. */
internal class RemotePublishedBatchReadback internal constructor(val body: JsonObject) {
    val grantsWriteAuthority: Boolean get() = false
    val isSavedReceipt: Boolean get() = false
    val allowsChunkOutput: Boolean get() = false
}

internal object DevicePublishedBatchReadbackEnvelope {
    const val KIND = DevicePublishedReadbackEnvelope.KIND
    private const val DESTINATION = "magnolie-published-readback-destination-v2\u0000"
    private const val BINDING = "magnolie-published-readback-binding-v2\u0000"
    private const val READBACK = "magnolie-published-readback-v2\u0000"
    private val fields = setOf("format", "offer_id", "manifest_sha256", "transfer_id", "source_id", "media_type", "members", "permission_epoch", "readback_nonce")
    private val memberFields = setOf("size", "sha256", "mime_type", "publication_sha256", "row_sha256")
    private val id = Regex("[0-9a-f]{32}")
    private val offerId = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
    private val positiveInteger = Regex("[1-9][0-9]*")
    private val mime = mapOf("images" to Regex("image/[a-z0-9.+-]{1,80}"), "video" to Regex("video/[a-z0-9.+-]{1,80}"))

    private fun text(value: JsonObject, key: String): String =
        (value[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()

    private fun context(value: JsonObject): JsonObject {
        if (value.keys != fields || value["format"] != JsonPrimitive(2) || !offerId.matches(text(value, "offer_id"))) fail()
        for (key in listOf("manifest_sha256", "permission_epoch", "readback_nonce")) if (!DeviceFileControl.hash(text(value, key))) fail()
        for (key in listOf("transfer_id", "source_id")) if (!id.matches(text(value, key))) fail()
        val expectedMime = mime[text(value, "media_type")] ?: fail()
        val members = value["members"] as? JsonObject ?: fail()
        if (members.size !in 1..DeviceFileManifest.MAX_FILES) fail()
        val publications = mutableSetOf<String>()
        val rows = mutableSetOf<String>()
        var total = 0L
        for ((fileId, raw) in members) {
            val member = raw as? JsonObject ?: fail()
            if (!id.matches(fileId) || member.keys != memberFields) fail()
            val size = (member["size"] as? JsonPrimitive)?.takeUnless { it.isString }?.content
                ?.takeIf(positiveInteger::matches)?.toLongOrNull() ?: fail()
            if (size !in 1..DeviceFileManifest.MAX_FILE_BYTES || !expectedMime.matches(text(member, "mime_type"))) fail()
            for (key in listOf("sha256", "publication_sha256", "row_sha256")) if (!DeviceFileControl.hash(text(member, key))) fail()
            if (!publications.add(text(member, "publication_sha256")) || !rows.add(text(member, "row_sha256"))) fail()
            total += size
        }
        if (total > DeviceFileManifest.MAX_TOTAL_BYTES) fail()
        return value
    }

    fun destinationToken(value: JsonObject): String = DeviceFileControl.digest(DESTINATION, context(value))

    fun encodeBody(value: JsonObject, binding: DeviceTransferBinding): JsonObject {
        if (binding.permissionEpoch != text(value, "permission_epoch") || binding.destinationToken != destinationToken(value)) fail()
        val body = JsonObject(value + mapOf("destination_token" to JsonPrimitive(binding.destinationToken),
            "binding_sha256" to JsonPrimitive(DeviceFileControl.digest(BINDING, binding.snapshot()))))
        return JsonObject(body + ("readback_sha256" to JsonPrimitive(DeviceFileControl.digest(READBACK, body))))
    }

    fun parse(message: JsonObject, offer: JsonObject, binding: DeviceTransferBinding, kind: GalleryMediaType,
        now: Long = System.currentTimeMillis()): RemotePublishedBatchReadback {
        if (TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX) fail()
        TelefonNachrichten.validateHeader(message, now)
        val created = message.long("created_ms")
        val expires = message.long("expires_ms")
        if (message.string("kind") != KIND || now >= expires || expires - created > DeviceFileControl.MAX_TTL_MS) fail()
        val body = message["body"] as? JsonObject ?: fail()
        if (body.keys != fields + setOf("destination_token", "binding_sha256", "readback_sha256") ||
            encodeBody(JsonObject(body.filterKeys { it in fields }), binding) != body) fail()
        val manifest = DeviceFileOfferEnvelope.validate(offer, binding.senderId, binding.receiverId, now)
        val members = body.getValue("members").jsonObject
        if (now < offer.long("created_ms") || now >= offer.long("expires_ms") || created < offer.long("created_ms") ||
            expires > offer.long("expires_ms") || body["offer_id"] != offer["message_id"] ||
            body["manifest_sha256"] != JsonPrimitive(manifest.fingerprint) || body["transfer_id"] != JsonPrimitive(manifest.transferId) ||
            body["source_id"] != JsonPrimitive(manifest.sourceId) || body["media_type"] != JsonPrimitive(kind.uriSegment) ||
            members.keys != manifest.files.map { it.id }.toSet()) fail()
        for (file in manifest.files) {
            val member = members.getValue(file.id).jsonObject
            if (member["size"] != JsonPrimitive(file.size) || member["sha256"] != JsonPrimitive(file.sha256)) fail()
        }
        return RemotePublishedBatchReadback(body)
    }

    private fun fail(): Nothing = DeviceFileControl.fail("file_published_batch_readback_invalid")
}
