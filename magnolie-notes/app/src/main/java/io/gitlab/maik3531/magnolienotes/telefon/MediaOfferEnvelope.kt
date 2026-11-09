package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Metadata only; native current intent, book, own control/OS rights and original
 * phone proofs are independently required by the existing incoming owner. */
internal data class NativeMediaOffer(val offer: JsonObject, val manifest: DeviceFileManifest,
    val settings: JsonObject, val kind: GalleryMediaType, val mimeTypes: Map<String, String>,
    val originals: Map<String, GalleryPhoneMediaReference>, val pcOrigins: Map<String, GalleryPcMediaOrigin> = emptyMap())

/** Opaque PC source correlation only; never a phone reference or row authority. */
internal class GalleryPcMediaOrigin private constructor(internal val body: JsonObject) {
    internal val origin: String get() = body.string("origin_sha256")
    internal val previousPublication: String? get() = (body["previous_publication_sha256"] as? JsonPrimitive)?.takeIf { it.isString }?.content
    companion object {
        internal fun parse(body: JsonObject): GalleryPcMediaOrigin {
            if (body.keys != setOf("format", "origin_sha256", "previous_publication_sha256") || body["format"] != JsonPrimitive(1) ||
                !DeviceFileControl.hash((body["origin_sha256"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: "")) fail()
            val previous = body["previous_publication_sha256"]
            if (previous != JsonNull && !DeviceFileControl.hash((previous as? JsonPrimitive)?.takeIf { it.isString }?.content ?: "")) fail()
            return GalleryPcMediaOrigin(body)
        }
        private fun fail(): Nothing = DeviceFileControl.fail("media_offer_pc_origin_invalid")
    }
}

internal object MediaOfferEnvelope {
    const val KIND = "file_transfer.media_offer"

    fun validate(message: JsonObject, senderId: String, receiverId: String,
        now: Long = System.currentTimeMillis()): NativeMediaOffer {
        if (TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX ||
            message["kind"] != JsonPrimitive(KIND) || now >= message.long("expires_ms")) fail()
        val body = message["body"] as? JsonObject ?: fail()
        val pcVersion = body["format"] == JsonPrimitive(2)
        if (body.keys != setOf("format", "offer", "settings", "media_type", "mime_types", "originals") +
            (if (pcVersion) setOf("pc_origins") else emptySet()) || !pcVersion && body["format"] != JsonPrimitive(1)) fail()
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
        val pc = if (pcVersion) body["pc_origins"] as? JsonObject ?: fail() else JsonObject(emptyMap())
        if (pcVersion && (pc.isEmpty() || MediaSyncSettings.effective(settings).string("collection_mode") != "entire_collection" ||
            pc.keys.any { it !in ids || it in references } || pc.keys + references.keys != ids)) fail()
        val pcOrigins = pc.mapValues { (_, value) -> GalleryPcMediaOrigin.parse(value as? JsonObject ?: fail()) }
        if (pcOrigins.values.map { it.origin }.distinct().size != pcOrigins.size) fail()
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
        return NativeMediaOffer(offer, manifest, settings, kind, types, originals, pcOrigins)
    }
    private fun fail(): Nothing = DeviceFileControl.fail("media_offer_invalid_envelope")
}
