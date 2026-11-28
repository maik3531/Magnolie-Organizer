package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Historical offer and Saved plus one fresh native control challenge. Parsing
 * grants no right to receive or to read a provider row. */
internal class NativeGallerySavedReadbackRequest private constructor(
    internal val original: JsonObject,
    internal val media: NativeMediaOffer,
    internal val saved: JsonObject,
    internal val nonce: String,
    internal val control: NativeFileOperationBinding,
    private val created: Long,
    internal val expires: Long
) {
    private val started = DeviceFileControl.monotonicMs()

    internal fun requireLive(now: Long = System.currentTimeMillis()) {
        if (now !in created until expires || DeviceFileControl.monotonicMs() - started !in 0L until (expires - created))
            fail()
    }

    companion object {
        const val KIND = "file_transfer.published.recover"
        private const val CONTROL_DOMAIN = "magnolie-pc-saved-readback-control-v1\u0000"
        private const val MAX_WALL = 253_402_300_799_999L

        internal fun parse(message: JsonObject, peerId: String, localId: String, mixed: Boolean,
            operationBinding: (String) -> NativeFileOperationBinding?, now: Long = System.currentTimeMillis()): NativeGallerySavedReadbackRequest {
            TelefonNachrichten.validateHeader(message, now)
            val created = message.long("created_ms"); val expires = message.long("expires_ms")
            if (message.string("kind") != KIND || now !in created until expires || created < 0 || expires > MAX_WALL ||
                expires - created > DeviceFileControl.MAX_TTL_MS || TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX)
                fail()
            val body = message["body"] as? JsonObject ?: fail()
            if (body.keys != setOf("format", "binding_sha256", "nonce", "offer", "saved") ||
                body["format"] != JsonPrimitive(1)) fail()
            val nonce = body.string("nonce")
            if (!DeviceFileControl.hash(nonce)) fail()
            val offer = body["offer"] as? JsonObject ?: fail()
            val historicalAt = offer.long("created_ms")
            val media = if (offer.getValue("body").jsonObject["format"] == JsonPrimitive(3))
                MediaOfferEnvelope.validateNewPcImageBatch(offer, peerId, localId, mixed = mixed, now = historicalAt)
            else MediaOfferEnvelope.validatePrivatePcVideoOriginal(offer, peerId, localId, now = historicalAt, mixed = mixed)
            val control = operationBinding(media.manifest.fingerprint) ?: fail()
            val binding = control.binding
            if (binding.senderId != peerId || binding.receiverId != localId ||
                binding.destinationToken != media.manifest.fingerprint ||
                body["binding_sha256"] != JsonPrimitive(DeviceFileControl.digest(CONTROL_DOMAIN, binding.snapshot()))) fail()
            val saved = body["saved"] as? JsonObject ?: fail()
            val savedAt = saved.long("created_ms")
            val receipt = DeviceFileSavedEnvelope.parse(saved, media.manifest, savedAt)
            if (savedAt !in historicalAt..created || receipt.expires > offer.long("expires_ms") ||
                receipt.members.map { it.receiptSha256 }.distinct().size != receipt.members.size) fail()
            return NativeGallerySavedReadbackRequest(offer, media, saved, nonce, control, created, expires)
        }

        private fun fail(): Nothing = DeviceFileControl.fail("media_saved_readback_invalid_request")
    }
}
