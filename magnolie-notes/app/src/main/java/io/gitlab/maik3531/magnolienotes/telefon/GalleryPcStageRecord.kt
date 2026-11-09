package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Protected cache membership only, never live receive/write or restart rights. */
internal class GalleryPcStageRecord private constructor(internal val body: JsonObject) {
    val plan: GalleryPcReplacementPlan get() = GalleryPcReplacementPlan.parse(body.getValue("plan").jsonObject)
    val id: String get() = plan.id
    val bytes: Long get() = body.long("bytes")
    val acceptance: GalleryIncomingAcceptance get() = GalleryIncomingAcceptance.parse(body.getValue("acceptance").jsonObject)
    val sealed: Boolean get() = body["state"] == JsonPrimitive("sealed")
    val grantsWriteAuthority: Boolean get() = false
    internal fun seal(witness: JsonObject, observed: NativeIncomingMediaObservation) = parse(JsonObject(body + mapOf(
        "state" to JsonPrimitive("sealed"), "seal" to witness, "observation" to buildJsonObject {
            put("media_type", observed.mediaType.uriSegment); put("mime_type", observed.mimeType)
            put("width", observed.width); put("height", observed.height)
            put("duration_ms", observed.durationMs?.let(::JsonPrimitive) ?: JsonNull)
        })))
    companion object {
        const val PREFIX = "gallery-pc-stage-v1/"
        const val MAX_RECORDS = 128
        internal fun create(plan: GalleryPcReplacementPlan, root: java.io.File, key: String, acceptance: GalleryIncomingAcceptance): GalleryPcStageRecord {
            val media = media(plan)
            return parse(buildJsonObject {
                put("format", 1); put("plan", plan.body); put("root_path", root.path); put("root_key", key)
                put("state", "reserved"); put("bytes", media.manifest.totalBytes); put("acceptance", acceptance.body)
                put("seal", JsonNull); put("observation", JsonNull)
            })
        }
        internal fun media(plan: GalleryPcReplacementPlan): NativeMediaOffer {
            val offer = plan.body.getValue("offer").jsonObject
            val binding = plan.body.getValue("binding").jsonObject
            return MediaOfferEnvelope.validate(offer, binding.string("sender_id"), binding.string("receiver_id"), offer.long("created_ms"))
        }
        internal fun parse(value: JsonObject): GalleryPcStageRecord = try {
            if (value.keys != setOf("format", "plan", "root_path", "root_key", "state", "bytes", "acceptance", "seal", "observation") ||
                value["format"] != JsonPrimitive(1)) fail()
            val plan = GalleryPcReplacementPlan.parse(value.getValue("plan").jsonObject); val media = media(plan)
            val root = value.string("root_path"); val key = value.string("root_key")
            val acceptance = GalleryIncomingAcceptance.parse(value.getValue("acceptance").jsonObject)
            val scope = GalleryIncomingScope.capture(media.manifest, media.kind, "entire_collection",
                plan.body.getValue("binding").jsonObject.string("sender_identity_sha256"), media.originals, media.pcOrigins) { emptyList() }
            if (!java.io.File(root).isAbsolute || '\u0000' in root || key.length !in 1..1024 ||
                value.long("bytes") != media.manifest.totalBytes || acceptance.body["binding"] != plan.body["binding"] ||
                acceptance.body["format"] != JsonPrimitive(2) || acceptance.body.string("scope_sha256") != scope.fingerprint(media.manifest) ||
                acceptance.body.string("transfer_id") != media.manifest.transferId || acceptance.body.string("media_type") != media.kind.uriSegment ||
                acceptance.body.long("file_count") != 1L || acceptance.body.long("total_bytes") != media.manifest.totalBytes ||
                acceptance.body.long("created_ms") < media.offer.long("created_ms") ||
                acceptance.body.string("manifest_sha256") != media.manifest.fingerprint ||
                acceptance.body.string("offer_id") != media.offer.string("message_id") ||
                acceptance.body.string("offer_sha256") != DeviceFileControl.digest("magnolie-incoming-offer-v1\u0000", media.offer) ||
                acceptance.expires > media.offer.long("expires_ms")) fail()
            when (value.string("state")) {
                "reserved" -> if (value["seal"] != JsonNull || value["observation"] != JsonNull) fail()
                "sealed" -> {
                    val seal = value.getValue("seal").jsonObject; val observed = value.getValue("observation").jsonObject
                    if (seal.keys != setOf("key", "size", "sha256") || seal.string("key").length !in 1..1024 ||
                        seal.long("size") !in 29..DeviceTransferProtection.MAX_CLEAR_BYTES.toLong() + 28 || !DeviceFileControl.hash(seal.string("sha256")) ||
                        observed.keys != setOf("media_type", "mime_type", "width", "height", "duration_ms") ||
                        observed.string("media_type") != media.kind.uriSegment || observed.string("mime_type") != media.mimeTypes.values.single() ||
                        observed.long("width") !in 1..1_000_000 || observed.long("height") !in 1..1_000_000 ||
                        observed.long("width") * observed.long("height") > 1_000_000_000 ||
                        (if (media.kind == GalleryMediaType.IMAGES) observed["duration_ms"] != JsonNull else observed.long("duration_ms") <= 0)) fail()
                }
                else -> fail()
            }
            GalleryPcStageRecord(value)
        } catch (_: Exception) { fail() }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_pc_stage_record_invalid")
    }
}
