package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Durable history of an explicitly ended attempt, never a source/READ grant.
 * The entire old head and exact command are preserved, not deleted or adopted. */
internal class PhotoSourceResumeAbandonment private constructor(val record: JsonObject) {
    val head: JsonObject get() = record["head"]!!.jsonObject
    val command: JsonObject get() = record["command"]!!.jsonObject
    val version: String get() = DeviceFileControl.digest("magnolie-gallery-resume-abandonment-v1\u0000", record)

    companion object {
        const val MAX_HISTORY = 8 // Full means HOLD; never silently evict original evidence.
        fun create(job: PhotoSourceJob, original: PhotoSourceRemoteAcceptance, head: PhotoSourceResumeAttempt,
            command: JsonObject, observedAt: Long): PhotoSourceResumeAbandonment = parse(buildJsonObject {
            put("format", 1); put("head", head.record); put("command", command); put("observed_at", observedAt)
        }, job, original)

        fun parse(record: JsonObject, job: PhotoSourceJob, original: PhotoSourceRemoteAcceptance): PhotoSourceResumeAbandonment {
            fun fail(): Nothing = DeviceFileControl.fail("photo_jobs_resume_abandonment_invalid")
            if (record.keys != setOf("format", "head", "command", "observed_at") || record["format"] != JsonPrimitive(1)) fail()
            val head = PhotoSourceResumeAttempt.parse(record["head"] as? JsonObject ?: fail(), job, original)
            val at = (record["observed_at"] as? JsonPrimitive)?.takeIf { !it.isString && Regex("[1-9][0-9]*").matches(it.content) }
                ?.content?.toLongOrNull() ?: fail()
            val command = DeviceFileSourceCommand.parse(record["command"] as? JsonObject ?: fail(), at)
            if (command.operation != "abandon_resume" || command.originalJobId != job.id ||
                command.originalJobVersion != original.record["source_job_sha256"]?.jsonPrimitive?.content ||
                command.attemptId != head.id || command.attemptSha256 != head.version) fail()
            return PhotoSourceResumeAbandonment(record)
        }
    }
}
