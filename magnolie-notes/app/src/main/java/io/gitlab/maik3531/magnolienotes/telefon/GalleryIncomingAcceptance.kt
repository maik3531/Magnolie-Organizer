package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.security.SecureRandom

/** Original native incoming acceptance intent. Historical storage is not live
 * receive permission, secure output completion or a Saved receipt. */
internal class GalleryIncomingAcceptance private constructor(internal val body: JsonObject) {
    internal val id: String get() = DeviceFileControl.digest("magnolie-gallery-incoming-acceptance-v1\u0000", body)
    internal val expires: Long get() = body.long("expires_ms")
    companion object {
        internal const val PREFIX = "gallery-incoming-acceptance-v1/"
        internal const val MAX_RECORDS = 128
        internal fun create(owner: NativeGalleryIncomingOwner, offer: JsonObject, now: Long): GalleryIncomingAcceptance {
            owner.requireCurrent()
            val manifest = DeviceFileOfferEnvelope.validate(offer, owner.binding.senderId, owner.binding.receiverId, now)
            if (manifest.wire() != owner.manifest.wire() || now >= offer.long("expires_ms")) fail()
            return parse(buildJsonObject {
                put("format", 1); put("binding", owner.binding.snapshot()); put("pairing_epoch", owner.pairingEpoch)
                put("manifest_sha256", manifest.fingerprint); put("transfer_id", manifest.transferId)
                put("offer_id", offer.string("message_id")); put("offer_sha256", DeviceFileControl.digest("magnolie-incoming-offer-v1\u0000", offer))
                put("media_type", owner.kind.uriSegment); put("file_count", manifest.files.size); put("total_bytes", manifest.totalBytes)
                put("created_ms", now); put("expires_ms", minOf(offer.long("expires_ms"), now + DeviceFileControl.MAX_TTL_MS))
                put("nonce", ByteArray(32).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(it) })
            })
        }
        internal fun parse(value: JsonObject): GalleryIncomingAcceptance {
            if (value.keys != setOf("format", "binding", "pairing_epoch", "manifest_sha256", "transfer_id", "offer_id", "offer_sha256",
                    "media_type", "file_count", "total_bytes", "created_ms", "expires_ms", "nonce") || value["format"] != JsonPrimitive(1)) fail()
            val binding = value["binding"] as? JsonObject ?: fail()
            if (binding.keys != setOf("sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token")) fail()
            DeviceTransferBinding(text(binding, "sender_id"), text(binding, "receiver_id"), text(binding, "sender_identity_sha256"), text(binding, "receiver_identity_sha256"),
                text(binding, "permission_epoch"), text(binding, "destination_token"))
            for (name in listOf("pairing_epoch", "manifest_sha256", "offer_sha256", "nonce")) if (!DeviceFileControl.hash(text(value, name))) fail()
            if (!Regex("[0-9a-f]{32}").matches(text(value, "transfer_id")) ||
                !Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(text(value, "offer_id")) ||
                GalleryMediaType.entries.none { it.uriSegment == text(value, "media_type") }) fail()
            fun number(name: String) = (value[name] as? JsonPrimitive)?.takeIf { !it.isString && Regex("0|[1-9][0-9]*").matches(it.content) }
                ?.content?.toLongOrNull() ?: fail()
            val created = number("created_ms"); val expires = number("expires_ms")
            if (number("file_count") !in 1..DeviceFileManifest.MAX_FILES || number("total_bytes") !in 1..DeviceFileManifest.MAX_TOTAL_BYTES ||
                created !in 0..253_402_300_739_999L || expires <= created || expires - created > DeviceFileControl.MAX_TTL_MS) fail()
            return GalleryIncomingAcceptance(value)
        }
        private fun text(value: JsonObject, name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_incoming_acceptance_invalid")
    }
}
