package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Authenticated historical attempt state. Even accepted is NOT a run/Chunk grant. */
internal class PhotoSourceResumeAttempt private constructor(val record: JsonObject) {
    val phase: String get() = (record["phase"] as JsonPrimitive).content
    val id: String get() = (record["attempt_id"] as JsonPrimitive).content
    val base: JsonObject get() = JsonObject(record - setOf("phase", "accepted_at", "acceptance"))
    val allowsChunkOutput: Boolean get() = false

    companion object {
        fun prepare(job: PhotoSourceJob, original: PhotoSourceRemoteAcceptance, id: String, offer: JsonObject) = parse(buildJsonObject {
            put("format", 1); put("job_id", job.id); put("source_job_sha256", job.version)
            put("source_context", job.sourceContext); put("root_key", job.rootKey?.let(::JsonPrimitive) ?: JsonNull)
            put("original_acceptance_sha256", DeviceFileControl.digest("magnolie-gallery-original-acceptance-v1\u0000", original.record))
            put("attempt_id", id); put("offer", offer); put("phase", "prepared"); put("accepted_at", JsonNull); put("acceptance", JsonNull)
        }, job, original)

        fun advance(previous: PhotoSourceResumeAttempt, phase: String, job: PhotoSourceJob, original: PhotoSourceRemoteAcceptance,
            message: JsonObject? = null, observedAt: Long? = null): PhotoSourceResumeAttempt {
            if (phase == "sent" && previous.phase !in setOf("prepared", "sent") ||
                phase == "accepted" && previous.phase !in setOf("sent", "accepted") || phase !in setOf("sent", "accepted"))
                DeviceFileControl.fail("photo_jobs_resume_attempt_phase_conflict")
            return parse(JsonObject(previous.record + mapOf(
                "phase" to JsonPrimitive(phase), "accepted_at" to (observedAt?.let(::JsonPrimitive) ?: JsonNull),
                "acceptance" to (message ?: JsonNull))), job, original)
        }

        fun parse(record: JsonObject, job: PhotoSourceJob, original: PhotoSourceRemoteAcceptance): PhotoSourceResumeAttempt {
            fun fail(): Nothing = DeviceFileControl.fail("photo_jobs_resume_attempt_invalid")
            fun text(name: String) = (record[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            if (record.keys != setOf("format", "job_id", "source_job_sha256", "source_context", "root_key", "original_acceptance_sha256",
                    "attempt_id", "offer", "phase", "accepted_at", "acceptance") || record["format"] != JsonPrimitive(1) ||
                job.phase !in setOf("sealed", "retired") || job.snapshot == null || job.rootKey == null || original.originalAuthority == null ||
                record["job_id"] != JsonPrimitive(job.id) || record["source_context"] != JsonPrimitive(job.sourceContext) ||
                record["root_key"] != JsonPrimitive(job.rootKey) || record["source_job_sha256"] != original.record["source_job_sha256"] ||
                job.phase == "sealed" && record["source_job_sha256"] != JsonPrimitive(job.version) ||
                record["original_acceptance_sha256"] != JsonPrimitive(DeviceFileControl.digest("magnolie-gallery-original-acceptance-v1\u0000", original.record))) fail()
            if (!Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(text("attempt_id"))) fail()
            val manifest = DeviceFileManifest.parse(job.snapshot["manifest"] as? JsonObject ?: fail())
            val offer = record["offer"] as? JsonObject ?: fail()
            val at = offer.long("created_ms")
            if (DeviceFileOfferEnvelope.validate(offer, manifest.senderId, manifest.receiverId, at).fingerprint != manifest.fingerprint) fail()
            val expected = original.historicalAcceptance()
            if (offer.string("message_id") == expected.offerId) fail()
            when (text("phase")) {
                "prepared", "sent" -> if (record["accepted_at"] != JsonNull || record["acceptance"] != JsonNull) fail()
                "accepted" -> {
                    val time = (record["accepted_at"] as? JsonPrimitive)?.takeIf { !it.isString && Regex("[1-9][0-9]*").matches(it.content) }
                        ?.content?.toLongOrNull() ?: fail()
                    if (time < at || time >= offer.long("expires_ms")) fail()
                    val accepted = DeviceFileAcceptanceEnvelope.parse(record["acceptance"] as? JsonObject ?: fail(), time)
                    if (accepted.offerId != offer.string("message_id") || accepted.transferId != expected.transferId ||
                        accepted.manifestSha256 != expected.manifestSha256 || accepted.acceptanceSha256 != expected.acceptanceSha256 ||
                        accepted.permissionEpoch != expected.permissionEpoch || accepted.destinationToken != expected.destinationToken) fail()
                }
                else -> fail()
            }
            return PhotoSourceResumeAttempt(record)
        }
    }
}

/** Held native index/attempt ownership, never produced by historical JSON parse. */
internal class NativeResumeAttemptStorage internal constructor(private val index: PhotoSourceJobIndex,
    private val owner: NativeGalleryResumeAttempt, private val job: PhotoSourceJob, private val base: JsonObject) {
    fun requireOutput(expected: NativeGalleryResumeAttempt) {
        if (expected !== owner) DeviceFileControl.fail("photo_jobs_resume_attempt_owner_changed")
        val state = index.requireResumeAttempt(job, base)
        if (state.phase !in setOf("prepared", "sent")) DeviceFileControl.fail("photo_jobs_resume_attempt_already_accepted")
    }
    fun sent(expected: NativeGalleryResumeAttempt, permitted: () -> Unit) {
        if (expected !== owner) DeviceFileControl.fail("photo_jobs_resume_attempt_owner_changed")
        index.advanceResumeAttempt(job, base, "sent", null, null, permitted)
    }
    fun requireSent(expected: NativeGalleryResumeAttempt) {
        if (expected !== owner) DeviceFileControl.fail("photo_jobs_resume_attempt_owner_changed")
        if (index.requireResumeAttempt(job, base).phase !in setOf("sent", "accepted"))
            DeviceFileControl.fail("photo_jobs_resume_offer_not_sent")
    }
    fun accepted(expected: NativeGalleryResumeAttempt, message: JsonObject, observedAt: Long, permitted: () -> Unit) {
        if (expected !== owner) DeviceFileControl.fail("photo_jobs_resume_attempt_owner_changed")
        index.advanceResumeAttempt(job, base, "accepted", message, observedAt, permitted)
    }
}
