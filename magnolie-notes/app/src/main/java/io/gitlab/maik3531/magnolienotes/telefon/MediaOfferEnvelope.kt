package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Metadata only; native current intent, book, own control/OS rights and original
 * phone proofs are independently required by the existing incoming owner. */
internal data class NativeMediaOffer(val offer: JsonObject, val manifest: DeviceFileManifest,
    val settings: JsonObject, val kind: GalleryMediaType, val mimeTypes: Map<String, String>,
    val originals: Map<String, GalleryPhoneMediaReference>)

internal object MediaOfferEnvelope {
    const val KIND = "file_transfer.media_offer"

    fun validate(message: JsonObject, senderId: String, receiverId: String,
        now: Long = System.currentTimeMillis()): NativeMediaOffer {
        if (TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX ||
            message["kind"] != JsonPrimitive(KIND) || now >= message.long("expires_ms")) fail()
        val body = message["body"] as? JsonObject ?: fail()
        if (body.keys != setOf("format", "offer", "settings", "media_type", "mime_types", "originals") || body["format"] != JsonPrimitive(1)) fail()
        val rawOffer = body["offer"] as? JsonObject ?: fail()
        val offer = JsonObject(message.toMutableMap().apply { put("kind", JsonPrimitive(DeviceFileOfferEnvelope.KIND)); put("body", rawOffer) })
        val manifest = DeviceFileOfferEnvelope.validate(offer, senderId, receiverId, now)
        val settings = body["settings"] as? JsonObject ?: fail()
        MediaSyncSettings.validateStart(buildJsonObject { put("format", 1); put("settings", settings) })
        val kind = GalleryMediaType.entries.singleOrNull { JsonPrimitive(it.uriSegment) == body["media_type"] } ?: fail()
        if (!MediaSyncSettings.transferRequestedFor(settings, kind.uriSegment, toPhone = true)) fail()
        val ids = manifest.files.map { it.id }.toSet()
        val mime = body["mime_types"] as? JsonObject ?: fail()
        val references = body["originals"] as? JsonObject ?: fail()
        if (mime.keys != ids || references.keys.any { it !in ids } ||
            MediaSyncSettings.effective(settings).string("collection_mode") == "phone_inventory" && references.keys != ids) fail()
        val types = mime.mapValues { (_, value) ->
            val text = (value as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            if (!kind.acceptsMime(text)) fail()
            text
        }
        val originals = references.mapValues { (_, value) ->
            val reference = GalleryPhoneMediaReference.parse(value as? JsonObject ?: fail())
            if (reference.body["media_type"] != JsonPrimitive(kind.uriSegment)) fail()
            reference
        }
        if (originals.values.map { it.body }.distinct().size != originals.size) fail()
        return NativeMediaOffer(offer, manifest, settings, kind, types, originals)
    }
    private fun fail(): Nothing = DeviceFileControl.fail("media_offer_invalid_envelope")
}
