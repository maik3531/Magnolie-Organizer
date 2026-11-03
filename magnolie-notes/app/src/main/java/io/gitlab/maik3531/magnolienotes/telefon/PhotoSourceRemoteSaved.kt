package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Protected historical remote assertion only. No source READ, baseline,
 * destination presence, local save receipt or quota-retirement authority. */
internal class PhotoSourceRemoteSaved private constructor(val record: JsonObject,
    val confirmation: RemoteSavedConfirmation) {
    companion object {
        fun capture(job: PhotoSourceJob, accepted: DeviceFileRemoteAcceptance, message: JsonObject): PhotoSourceRemoteSaved {
            val record = buildJsonObject {
                put("format", 1); put("job_id", job.id); put("source_job_sha256", job.version)
                put("source_context", job.sourceContext); put("root_key", job.rootKey?.let(::JsonPrimitive) ?: JsonNull)
                put("acceptance", buildJsonObject {
                    put("offer_id", accepted.offerId); put("manifest_sha256", accepted.manifestSha256)
                    put("transfer_id", accepted.transferId); put("acceptance_sha256", accepted.acceptanceSha256)
                    put("permission_epoch", accepted.permissionEpoch); put("destination_token", accepted.destinationToken)
                    put("expires", accepted.expires); put("command_digest", accepted.commandDigest)
                })
                put("saved_message", message)
            }
            return parse(record, job)
        }

        fun parse(record: JsonObject, job: PhotoSourceJob): PhotoSourceRemoteSaved {
            fun fail(): Nothing = DeviceFileControl.fail("photo_jobs_remote_saved_invalid")
            if (job.phase !in setOf("sealed", "retired") || job.snapshot == null || job.rootKey == null ||
                record.keys != setOf("format", "job_id", "source_job_sha256", "source_context", "root_key", "acceptance", "saved_message") ||
                record["format"] != JsonPrimitive(1) || record["job_id"] != JsonPrimitive(job.id) ||
                record["source_context"] != JsonPrimitive(job.sourceContext) || record["root_key"] != JsonPrimitive(job.rootKey)) fail()
            fun text(value: JsonObject, name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            val jobHash = text(record, "source_job_sha256")
            if (!DeviceFileControl.hash(jobHash) || job.phase == "sealed" && jobHash != job.version) fail()
            val manifest = DeviceFileManifest.parse(job.snapshot["manifest"] as? JsonObject ?: fail())
            val accepted = record["acceptance"] as? JsonObject ?: fail()
            if (accepted.keys != setOf("offer_id", "manifest_sha256", "transfer_id", "acceptance_sha256", "permission_epoch", "destination_token", "expires", "command_digest")) fail()
            if (!Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(text(accepted, "offer_id"))) fail()
            for (name in listOf("manifest_sha256", "acceptance_sha256", "permission_epoch", "destination_token", "command_digest"))
                if (!DeviceFileControl.hash(text(accepted, name))) fail()
            val expires = (accepted["expires"] as? JsonPrimitive)?.takeIf { !it.isString && Regex("[1-9][0-9]*").matches(it.content) }
                ?.content?.toLongOrNull() ?: fail()
            if (expires <= 0 || accepted["manifest_sha256"] != JsonPrimitive(manifest.fingerprint) ||
                accepted["transfer_id"] != JsonPrimitive(manifest.transferId)) fail()
            val message = record["saved_message"] as? JsonObject ?: fail()
            // Validate original bounded envelope at its original observation
            // time, never renew its expiry or treat this historical read as IPC.
            val observed = message.long("created_ms")
            val confirmation = DeviceFileSavedEnvelope.parse(message, manifest, observed)
            if (accepted["acceptance_sha256"] != JsonPrimitive(confirmation.acceptanceSha256) ||
                accepted["permission_epoch"] != JsonPrimitive(confirmation.permissionEpoch) ||
                accepted["destination_token"] != JsonPrimitive(confirmation.destinationToken)) fail()
            return PhotoSourceRemoteSaved(record, confirmation)
        }
    }
}
