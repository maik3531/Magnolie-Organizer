package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Historical native observation, not a restarted offer/READ/Chunk grant. */
internal class PhotoSourceRemoteAcceptance private constructor(val record: JsonObject) {
    val acceptance: JsonObject get() = record["acceptance"] as JsonObject
    val originalAuthority: NativePhotoSourceContext? get() = (record["source_authority"] as? JsonObject)?.let {
        NativePhotoSourceContext.parse(it, (record["source_context"] as JsonPrimitive).content)
    }
    companion object {
        fun acceptanceWire(accepted: DeviceFileRemoteAcceptance) = buildJsonObject {
            put("offer_id", accepted.offerId); put("manifest_sha256", accepted.manifestSha256)
            put("transfer_id", accepted.transferId); put("acceptance_sha256", accepted.acceptanceSha256)
            put("permission_epoch", accepted.permissionEpoch); put("destination_token", accepted.destinationToken)
            put("expires", accepted.expires); put("command_digest", accepted.commandDigest)
        }

        fun capture(job: PhotoSourceJob, offer: NativeGalleryOfferOutput, accepted: DeviceFileRemoteAcceptance,
            lease: NativePhotoSourceLease) = parse(buildJsonObject {
            put("format", 2); put("job_id", job.id); put("source_job_sha256", job.version)
            put("source_context", job.sourceContext); put("root_key", job.rootKey?.let(::JsonPrimitive) ?: JsonNull)
            put("source_authority", NativePhotoSourceContext.parse(NativePhotoSourceContext.wire(lease), job.sourceContext).record)
            put("offer", buildJsonObject {
                put("message_id", offer.messageId); put("transfer_id", offer.transferId)
                put("manifest_sha256", offer.manifestSha256); put("expires", offer.expires)
            })
            put("acceptance", acceptanceWire(accepted))
        }, job)

        fun parse(record: JsonObject, job: PhotoSourceJob): PhotoSourceRemoteAcceptance {
            fun fail(): Nothing = DeviceFileControl.fail("photo_jobs_remote_acceptance_invalid")
            fun text(value: JsonObject, key: String) = (value[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            fun expires(value: JsonObject) = (value["expires"] as? JsonPrimitive)?.takeIf { !it.isString && Regex("[1-9][0-9]*").matches(it.content) }
                ?.content?.toLongOrNull()?.takeIf { it > 0 } ?: fail()
            val witnessed = when (record["format"]) { JsonPrimitive(1) -> false; JsonPrimitive(2) -> true; else -> fail() }
            if (job.phase !in setOf("sealed", "retired") || job.snapshot == null || job.rootKey == null ||
                record.keys != setOf("format", "job_id", "source_job_sha256", "source_context", "root_key", "offer", "acceptance") +
                    (if (witnessed) setOf("source_authority") else emptySet()) || record["job_id"] != JsonPrimitive(job.id) ||
                record["source_context"] != JsonPrimitive(job.sourceContext) || record["root_key"] != JsonPrimitive(job.rootKey)) fail()
            val jobHash = text(record, "source_job_sha256")
            if (!DeviceFileControl.hash(jobHash) || job.phase == "sealed" && jobHash != job.version) fail()
            val manifest = DeviceFileManifest.parse(job.snapshot["manifest"] as? JsonObject ?: fail())
            val offer = record["offer"] as? JsonObject ?: fail()
            val accepted = record["acceptance"] as? JsonObject ?: fail()
            if (offer.keys != setOf("message_id", "transfer_id", "manifest_sha256", "expires") ||
                accepted.keys != setOf("offer_id", "manifest_sha256", "transfer_id", "acceptance_sha256", "permission_epoch", "destination_token", "expires", "command_digest")) fail()
            if (!Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(text(offer, "message_id")) ||
                offer["message_id"] != accepted["offer_id"] || offer["manifest_sha256"] != JsonPrimitive(manifest.fingerprint) ||
                offer["transfer_id"] != JsonPrimitive(manifest.transferId) || accepted["manifest_sha256"] != offer["manifest_sha256"] ||
                accepted["transfer_id"] != offer["transfer_id"]) fail()
            expires(offer); expires(accepted)
            for (name in listOf("manifest_sha256", "acceptance_sha256", "permission_epoch", "destination_token", "command_digest"))
                if (!DeviceFileControl.hash(text(accepted, name))) fail()
            if (witnessed) {
                val authority = NativePhotoSourceContext.parse(record["source_authority"] as? JsonObject ?: fail(), job.sourceContext)
                if (authority.receiverId != manifest.receiverId || accepted["permission_epoch"] != JsonPrimitive(authority.permissionEpoch)) fail()
            }
            return PhotoSourceRemoteAcceptance(record)
        }
    }
}
