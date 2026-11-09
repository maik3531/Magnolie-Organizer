package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Durable proposed intent ONLY. Never acceptance, staging-read permission,
 * an OS grant, a writer, or authority to resume a process's old action. */
internal class GalleryPcReplacementPlan private constructor(internal val body: JsonObject) {
    val id: String get() = body.string("id")
    val predecessor: GalleryIncomingPublication get() = GalleryIncomingPublication.parse(body.getValue("predecessor").jsonObject)
    val grantsWriteAuthority: Boolean get() = false
    val grantsChunkAuthority: Boolean get() = false
    companion object {
        const val PREFIX = "gallery-pc-replacement-plan-v1/"
        const val MAX_RECORDS = 128
        internal fun create(original: GalleryIncomingPublication, entry: NativeGalleryArchiveEntry, bookVersion: String,
            binding: DeviceTransferBinding, offer: JsonObject): GalleryPcReplacementPlan = parse(buildJsonObject {
            put("format", 1); put("id", java.util.UUID.randomUUID().toString().replace("-", "")); put("state", "proposed")
            put("predecessor", original.body); put("offer", offer); put("binding", binding.snapshot()); put("book_version", bookVersion)
            put("archive", buildJsonObject { put("id", entry.id); put("version", entry.version); put("size", entry.bytes); put("sha256", entry.sha256) })
        })
        internal fun parse(value: JsonObject): GalleryPcReplacementPlan = try { parseStrict(value) }
            catch (_: Exception) { fail() }
        private fun parseStrict(value: JsonObject): GalleryPcReplacementPlan {
            if (value.keys != setOf("format", "id", "state", "predecessor", "offer", "binding", "book_version", "archive") ||
                value["format"] != JsonPrimitive(1) || value["state"] != JsonPrimitive("proposed") ||
                !Regex("[0-9a-f]{32}").matches(value.string("id")) || !DeviceFileControl.hash(value.string("book_version"))) fail()
            val original = GalleryIncomingPublication.parse(value.getValue("predecessor").jsonObject)
            if (original.pcOrigin == null || original.state != "published" || original.row == null) fail()
            val oldBinding = original.body.getValue("origin").jsonObject.getValue("binding").jsonObject
            val rawBinding = value.getValue("binding").jsonObject
            if (rawBinding.keys != setOf("sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token")) fail()
            val binding = DeviceTransferBinding(rawBinding.string("sender_id"), rawBinding.string("receiver_id"), rawBinding.string("sender_identity_sha256"),
                rawBinding.string("receiver_identity_sha256"), rawBinding.string("permission_epoch"), rawBinding.string("destination_token"))
            if (listOf("sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256").any { rawBinding[it] != oldBinding[it] }) fail()
            val offer = value.getValue("offer").jsonObject
            // Historical structural decoding, NOT a current offer admission or a renewed clock.
            val media = MediaOfferEnvelope.validate(offer, binding.senderId, binding.receiverId, offer.long("created_ms"))
            val file = media.manifest.files.singleOrNull() ?: fail()
            val pc = media.pcOrigins[file.id] ?: fail()
            if (media.originals.isNotEmpty() || pc.origin != original.pcOrigin!!.origin || pc.previousPublication != original.fingerprint ||
                media.kind.uriSegment != original.body.string("media_type") || media.mimeTypes[file.id] != original.body.string("mime_type") ||
                file.path.substringAfterLast('/') != original.body.string("name") || file.sha256 == original.body.string("sha256") || binding.destinationToken != media.manifest.fingerprint ||
                media.manifest.transferId == original.body.getValue("origin").jsonObject.string("transfer_id")) fail()
            val archive = value.getValue("archive").jsonObject
            if (archive.keys != setOf("id", "version", "size", "sha256") ||
                !Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}").matches(archive.string("id")) ||
                !DeviceFileControl.hash(archive.string("version")) || archive["size"] != original.body["size"] || archive["sha256"] != original.body["sha256"]) fail()
            return GalleryPcReplacementPlan(value)
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_pc_replacement_plan_invalid")
    }
}
