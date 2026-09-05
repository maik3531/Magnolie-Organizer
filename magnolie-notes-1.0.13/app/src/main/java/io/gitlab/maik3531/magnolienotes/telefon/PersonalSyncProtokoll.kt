package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.PersonalSync
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncClock
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncRecord
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import java.util.UUID
import java.util.Base64

/** Strict wire codec for personal data inside magnolie-phone/1 only. */
object PersonalSyncProtokoll {
    const val CHUNK_RAW = 180_000
    private const val MAX_TIMESTAMP = 253_402_300_799_999L
    private const val MAX_SAFE_INTEGER = 9_007_199_254_740_991L
    private val sha = Regex("[0-9a-f]{64}")
    private val kinds = setOf("note", "task", "notebook")
    private val deletionKinds = kinds + "attachment"

    fun validate(kind: String, body: JsonObject) {
        when (kind) {
            "personal_sync.settings" -> {
                TelefonNachrichten.exact(body, setOf("format", "own_device"))
                if (body.integer("format") != 1L || (body["own_device"] as? JsonPrimitive)?.booleanOrNull == null) fail()
            }
            "personal_sync.request" -> {
                TelefonNachrichten.exact(body, setOf("format", "run_id", "trigger", "modules"))
                TelefonNachrichten.uuid4(body.string("run_id")); if (body.integer("format") !in 1L..3L ||
                    body.string("trigger") !in setOf("manual", "auto_wifi")) fail()
                val modules = (body["modules"] as? JsonArray)?.map { (it as? JsonPrimitive)?.content } ?: fail()
                if (modules !in listOf(listOf("notes"), listOf("tasks"), listOf("notes", "tasks"))) fail()
            }
            "personal_sync.batch" -> decodeBatch(body)
            "personal_sync.report" -> validateReport(body)
            "personal_sync.attachment_request" -> validateAttachmentRequest(body)
            "personal_sync.attachment_chunk" -> validateAttachmentChunk(body)
            "personal_sync.attachment_result" -> validateAttachmentResult(body)
            "personal_sync.deletion_proposals" -> decodeDeletionProposals(body)
            "personal_sync.deletion_decision" -> decodeDeletionDecisions(body)
            else -> fail()
        }
    }

    data class DeletionProposal(val proposalId: String, val kind: String, val id: String,
        val parentId: String, val clock: List<PersonalSyncClock>, val priorHash: String,
        val deletedMs: Long, val label: String)
    data class DeletionDecision(val proposalId: String, val decision: String,
        val expectedClock: List<PersonalSyncClock>)

    fun decodeDeletionProposals(body: JsonObject): List<DeletionProposal> {
        TelefonNachrichten.exact(body, setOf("format", "run_id", "proposal_batch_id", "sequence", "last", "proposals"))
        if (body.integer("format") != 1L) fail(); TelefonNachrichten.uuid4(body.string("run_id"))
        TelefonNachrichten.uuid4(body.string("proposal_batch_id"))
        if (body.integer("sequence") !in 0..100_000 || (body["last"] as? JsonPrimitive)?.booleanOrNull == null ||
            TelefonKanonisch.bytes(body).size > 192 * 1024) fail()
        val values = (body["proposals"] as? JsonArray)?.takeIf { it.size <= 32 } ?: fail()
        val result = values.map { raw ->
            val value = raw as? JsonObject ?: fail()
            TelefonNachrichten.exact(value, setOf("proposal_id", "kind", "id", "parent_id", "clock", "prior_hash", "deleted_ms", "label"))
            TelefonNachrichten.uuid4(value.string("proposal_id")); val kind = value.string("kind")
            val id = value.string("id"); val parent = value.string("parent_id"); val label = value.string("label")
            if (kind !in deletionKinds || !identifier(id) || !identifier(parent, allowEmpty = true) ||
                (kind == "attachment") != parent.isNotEmpty() ||
                !sha.matches(value.string("prior_hash")) || value.integer("deleted_ms") !in 0..MAX_TIMESTAMP ||
                label.toByteArray().size > 240 || label.any { it.code < 32 || it.code == 127 }) fail()
            DeletionProposal(value.string("proposal_id"), kind, id, parent, decodeClock(value["clock"]),
                value.string("prior_hash"), value.long("deleted_ms"), label)
        }
        if (result.map { it.proposalId } != result.map { it.proposalId }.distinct().sortedWith(PersonalSync::compareUtf8)) fail()
        return result
    }

    fun decodeDeletionDecisions(body: JsonObject): List<DeletionDecision> {
        TelefonNachrichten.exact(body, setOf("format", "run_id", "decision_id", "decisions"))
        if (body.integer("format") != 1L) fail(); TelefonNachrichten.uuid4(body.string("run_id")); TelefonNachrichten.uuid4(body.string("decision_id"))
        val values = (body["decisions"] as? JsonArray)?.takeIf { it.size in 1..32 } ?: fail()
        val result = values.map { raw -> val value = raw as? JsonObject ?: fail()
            TelefonNachrichten.exact(value, setOf("proposal_id", "decision", "expected_clock")); TelefonNachrichten.uuid4(value.string("proposal_id"))
            if (value.string("decision") !in setOf("delete", "restore")) fail()
            DeletionDecision(value.string("proposal_id"), value.string("decision"), decodeClock(value["expected_clock"])) }
        if (result.map { it.proposalId } != result.map { it.proposalId }.distinct().sortedWith(PersonalSync::compareUtf8) ||
            TelefonKanonisch.bytes(body).size > 192 * 1024) fail()
        return result
    }

    private fun decodeClock(raw: kotlinx.serialization.json.JsonElement?): List<PersonalSyncClock> {
        val result = (raw as? JsonArray)?.map { item -> val value = item as? JsonObject ?: fail()
            TelefonNachrichten.exact(value, setOf("actor_id", "counter")); TelefonNachrichten.uuid4(value.string("actor_id"))
            if (value.integer("counter") !in 1..MAX_SAFE_INTEGER) fail()
            PersonalSyncClock(value.string("actor_id"), value.long("counter")) } ?: fail()
        if (result.size !in 1..16 || result != result.sortedWith { a, b -> PersonalSync.compareUtf8(a.actor_id, b.actor_id) } ||
            result.distinctBy { it.actor_id }.size != result.size) fail()
        return result
    }

    fun decodeBatch(body: JsonObject): List<PersonalSyncRecord> {
        val format = body.integer("format")
        TelefonNachrichten.exact(body, setOf("format", "run_id", "batch_id", "sequence", "last", "reply", "records") +
            if (format >= 2L) setOf("records_hash") else emptySet())
        TelefonNachrichten.uuid4(body.string("run_id")); TelefonNachrichten.uuid4(body.string("batch_id"))
        if (format !in 1L..3L || body.integer("sequence") !in 0..100_000 ||
            (body["last"] as? JsonPrimitive)?.booleanOrNull == null ||
            (body["reply"] as? JsonPrimitive)?.booleanOrNull == null || TelefonKanonisch.bytes(body).size > 192 * 1024) fail()
        val raw = body["records"] as? JsonArray ?: fail()
        if (raw.size > 32) fail()
        if (format >= 2L && !sha.matches(body.string("records_hash"))) fail()
        val result = raw.map { decodeRecord(it as? JsonObject ?: fail(), format.toInt()) }
        if (result.map { it.kind to it.id } != result.map { it.kind to it.id }.distinct().sortedWith { a, b ->
                PersonalSync.compareUtf8(a.first, b.first).takeIf { it != 0 } ?:
                    PersonalSync.compareUtf8(a.second, b.second) }) fail()
        return result
    }

    fun validateBatchForRequest(request: JsonObject, batch: JsonObject): List<PersonalSyncRecord> {
        validate("personal_sync.request", request)
        val records = decodeBatch(batch)
        if (request.string("run_id") != batch.string("run_id") ||
            request.integer("format") != batch.integer("format")) fail()
        val modules = (request["modules"] as JsonArray).map { (it as JsonPrimitive).content }.toSet()
        if (records.any { (it.kind == "task" && "tasks" !in modules) ||
                (it.kind in setOf("note", "notebook") && "notes" !in modules) }) fail()
        return records
    }

    fun batch(runId: String, records: List<PersonalSyncRecord>, sequence: Int, last: Boolean, reply: Boolean,
              format: Int = 1, recordsHash: String = "") = buildJsonObject {
        put("format", JsonPrimitive(format)); put("run_id", JsonPrimitive(runId)); put("batch_id", JsonPrimitive(UUID.randomUUID().toString()))
        if (format >= 2) put("records_hash", JsonPrimitive(recordsHash))
        put("sequence", JsonPrimitive(sequence)); put("last", JsonPrimitive(last)); put("reply", JsonPrimitive(reply))
        put("records", JsonArray(records.map { record -> buildJsonObject {
            put("kind", JsonPrimitive(record.kind)); put("id", JsonPrimitive(record.id)); put("state", JsonPrimitive("live"))
            put("clock", JsonArray(record.clock.map { buildJsonObject { put("actor_id", JsonPrimitive(it.actor_id)); put("counter", JsonPrimitive(it.counter)) } }))
            put("hash", JsonPrimitive(record.hash)); put("modified_ms", JsonPrimitive(record.modifiedMs)); put("value", record.value)
        }}))
    }

    private fun decodeRecord(value: JsonObject, format: Int): PersonalSyncRecord {
        TelefonNachrichten.exact(value, setOf("kind", "id", "state", "clock", "hash", "modified_ms", "value"))
        val kind = value.string("kind"); val id = value.string("id"); val digest = value.string("hash")
        if (kind !in kinds || !identifier(id) || value.string("state") != "live" ||
            !sha.matches(digest) || value.integer("modified_ms") !in 0..MAX_TIMESTAMP) fail()
        val clock = (value["clock"] as? JsonArray)?.map { item ->
            val objectValue = item as? JsonObject ?: fail()
            TelefonNachrichten.exact(objectValue, setOf("actor_id", "counter"))
            TelefonNachrichten.uuid4(objectValue.string("actor_id"));
            if (objectValue.integer("counter") !in 1..MAX_SAFE_INTEGER) fail()
            PersonalSyncClock(objectValue.string("actor_id"), objectValue.long("counter"))
        } ?: fail()
        if (clock.size !in 1..16 || clock != clock.sortedWith { a, b ->
                PersonalSync.compareUtf8(a.actor_id, b.actor_id) } ||
            clock.distinctBy { it.actor_id }.size != clock.size) fail()
        val projection = value["value"] as? JsonObject ?: fail()
        validateValue(kind, projection, format)
        if (PersonalSync.hash(projection) != digest || projection.long("modified_ms") != value.long("modified_ms")) fail()
        return PersonalSyncRecord(kind, id, clock, digest, value.long("modified_ms"), projection)
    }

    private fun validateValue(kind: String, value: JsonObject, format: Int) {
        val fields = when (kind) {
            "note" -> setOf("title", "text", "html", "notebook_id", "symbol", "created_ms", "modified_ms") +
                if (format >= 2) setOf("attachments") else emptySet()
            "task" -> setOf("title", "note", "due", "priority", "completed", "remind", "lead_days", "reminder_minute", "created_ms", "modified_ms") +
                if (format == 3) setOf("uid", "parent_uid", "order") else emptySet()
            else -> setOf("name", "modified_ms")
        }
        TelefonNachrichten.exact(value, fields)
        value.forEach { (name, raw) ->
            if (name == "attachments") {
                val attachments = raw as? JsonArray ?: fail()
                if (attachments.size > 64) fail()
                val ids = attachments.map { validateDescriptor(it as? JsonObject ?: fail()) }
                if (ids.distinct().size != ids.size) fail()
                return@forEach
            }
            val primitive = raw as? JsonPrimitive ?: fail()
            if (name in setOf("completed", "remind")) { if (primitive.booleanOrNull == null) fail() }
            else if (name.endsWith("_ms") || name in setOf("priority", "lead_days", "reminder_minute", "order")) {
                val number = primitive.integerOrNull()
                if (number == null || number < 0 || number > MAX_SAFE_INTEGER ||
                    name.endsWith("_ms") && number > MAX_TIMESTAMP) fail()
            } else if (!primitive.isString || primitive.content.toByteArray(Charsets.UTF_8).size >
                (if (name in setOf("notebook_id", "symbol", "due", "uid", "parent_uid")) 160 else 128 * 1024)) fail()
            else if (name in setOf("notebook_id", "uid", "parent_uid") && primitive.content != primitive.content.trim()) fail()
        }
        if (kind == "task" && (value.long("priority") !in 1..3 || value.long("lead_days") > 365 ||
                value.long("reminder_minute") > 1439 || value.string("due").let { it.isNotEmpty() && !Regex("\\d{4}-\\d{2}-\\d{2}").matches(it) })) fail()
    }

    private fun validateReport(body: JsonObject) {
        val format = body.integer("format")
        TelefonNachrichten.exact(body, setOf("format", "run_id", "state", "trigger", "transport", "sent", "received",
            "conflicts", "attachments_omitted", "oversized_skipped", "started_ms", "finished_ms", "error") +
            setOf("deletions") + if (format >= 2L) setOf("attachments") else emptySet())
        TelefonNachrichten.uuid4(body.string("run_id"))
        if (format !in 1L..3L || body.string("state") !in setOf("complete", "partial", "blocked", "failed") ||
            body.string("trigger") !in setOf("manual", "auto_wifi") || body.string("transport") !in setOf("wifi", "bluetooth") ||
            body.string("error") !in setOf("none", "offline", "not_granted", "too_large", "save_failed", "protocol", "unknown") ||
            body.integer("finished_ms") < body.integer("started_ms") ||
            listOf("conflicts", "attachments_omitted", "oversized_skipped").any {
                body.integer(it) !in 0..MAX_SAFE_INTEGER } ||
            listOf("started_ms", "finished_ms").any { body.integer(it) !in 0..MAX_TIMESTAMP }) fail()
        for (name in listOf("sent", "received")) {
            val counts = body[name] as? JsonObject ?: fail()
            TelefonNachrichten.exact(counts, setOf("notes", "tasks", "notebooks"))
            if (counts.values.any { primitive -> (primitive as? JsonPrimitive)?.let {
                    it.integerOrNull()?.let { number -> number !in 0..MAX_SAFE_INTEGER } != false } != false }) fail()
        }
        if (format >= 2L) {
            val counts = body["attachments"] as? JsonObject ?: fail()
            TelefonNachrichten.exact(counts, setOf("declared", "requested", "sent", "received", "reused", "preserved", "failed", "bytes"))
            if (counts.values.any { (it as? JsonPrimitive)?.integerOrNull() !in 0..MAX_SAFE_INTEGER }) fail()
        }
        val deletions = body["deletions"] as? JsonObject ?: fail()
        TelefonNachrichten.exact(deletions, setOf("pending", "deleted", "restored", "conflicts", "blocked", "trash"))
        if (listOf("pending", "deleted", "restored", "conflicts", "blocked").any {
                deletions.integer(it) !in 0..MAX_SAFE_INTEGER }) fail()
        val trash = deletions["trash"] as? JsonObject ?: fail()
        TelefonNachrichten.exact(trash, setOf("notes", "tasks", "notebooks", "attachments"))
        if (trash.values.any { (it as? JsonPrimitive)?.integerOrNull() !in 0..MAX_SAFE_INTEGER }) fail()
    }

    private fun validateDescriptor(value: JsonObject): String {
        TelefonNachrichten.exact(value, setOf("attachment_id", "name", "kind", "mime", "size", "sha256"))
        val id = value.string("attachment_id"); val name = value.string("name"); val mime = value.string("mime")
        val expected = mapOf("image/jpeg" to "image", "image/png" to "image", "image/webp" to "image",
            "image/gif" to "image", "application/pdf" to "pdf")[mime]
        if (!identifier(id) || name.isEmpty() || name.toByteArray().size > 720 ||
            name.any { it.code < 32 || it.code == 127 || it == '/' || it == '\\' } || value.string("kind") != expected ||
            value.integer("size") !in 1..8_388_608 || !sha.matches(value.string("sha256"))) fail()
        return id
    }

    private fun attachmentIdentity(body: JsonObject, fields: Set<String>) {
        TelefonNachrichten.exact(body, fields)
        if (body.integer("format") != 2L) fail()
        TelefonNachrichten.uuid4(body.string("run_id"))
        if ((body["reply"] as? JsonPrimitive)?.booleanOrNull == null || !sha.matches(body.string("records_hash"))) fail()
    }

    private fun validateAttachmentRequest(body: JsonObject) {
        attachmentIdentity(body, setOf("format", "run_id", "reply", "records_hash", "wants"))
        val wants = body["wants"] as? JsonArray ?: fail(); if (wants.size !in 1..64) fail()
        val hashes = wants.map { raw ->
            val want = raw as? JsonObject ?: fail()
            TelefonNachrichten.exact(want, setOf("sha256", "ranges")); val hash = want.string("sha256")
            if (!sha.matches(hash)) fail()
            val ranges = want["ranges"] as? JsonArray ?: fail(); if (ranges.size !in 1..128) fail()
            var previous = -1L
            ranges.forEach { rangeRaw ->
                val range = rangeRaw as? JsonArray ?: fail(); if (range.size != 2) fail()
                val start = (range[0] as? JsonPrimitive)?.integerOrNull() ?: fail()
                val end = (range[1] as? JsonPrimitive)?.integerOrNull() ?: fail()
                if (start !in 0 until end || end > 47 || start < previous) fail(); previous = end
            }; hash
        }
        if (hashes != hashes.distinct().sortedWith(PersonalSync::compareUtf8)) fail()
    }

    private fun validateAttachmentChunk(body: JsonObject) {
        attachmentIdentity(body, setOf("format", "run_id", "reply", "records_hash", "sha256", "index", "data"))
        if (!sha.matches(body.string("sha256")) || body.integer("index") !in 0..46) fail()
        val encoded = body.string("data")
        val raw = runCatching { Base64.getDecoder().decode(encoded) }.getOrNull() ?: fail()
        if (raw.size !in 1..CHUNK_RAW || Base64.getEncoder().encodeToString(raw) != encoded || TelefonKanonisch.bytes(body).size > 192 * 1024) fail()
    }

    private fun validateAttachmentResult(body: JsonObject) {
        attachmentIdentity(body, setOf("format", "run_id", "reply", "records_hash", "sha256", "state", "error"))
        val state = body.string("state"); val error = body.string("error")
        if (!sha.matches(body.string("sha256")) || state !in setOf("complete", "failed") ||
            error !in setOf("none", "not_found", "invalid", "too_large", "save_failed") || (state == "complete") != (error == "none")) fail()
    }

    private fun JsonObject.integer(name: String): Long =
        (getValue(name) as? JsonPrimitive)?.integerOrNull() ?: fail()

    private fun JsonPrimitive.integerOrNull(): Long? = takeIf { !isString &&
        Regex("0|[1-9][0-9]*").matches(content) }?.content?.toLongOrNull()

    private fun identifier(value: String, allowEmpty: Boolean = false): Boolean =
        value.toByteArray(Charsets.UTF_8).size <= 160 && '\u0000' !in value && value == value.trim() &&
            (allowEmpty || value.isNotEmpty())

    private fun fail(): Nothing = throw TelefonProtokollFehler("Ungültiges Personal-Sync-Schema.")
}
