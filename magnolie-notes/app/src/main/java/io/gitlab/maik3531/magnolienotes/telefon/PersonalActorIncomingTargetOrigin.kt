package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Volatile bounded origin metadata, NOT data, review/save or ACK authority.
 * TelefonWerk alone inserts into its private map from authenticated receive.
 * No book/provider callback or plaintext document snapshot is retained here. */
internal class PersonalActorIncomingTargetOrigin(private val runId: String, private val source: String,
    scope: JsonObject, nowMs: Long, elapsedMs: Long) {
    private val scope = Json.parseToJsonElement(scope.toString()).jsonObject
    private val wallDeadline = nowMs + 30000
    private val monotonicDeadline = elapsedMs + 30000
    private val frames = linkedMapOf<String, ByteArray>()
    private var byteCount = 0
    private var targetCount = 0
    private var invalid = false

    init { PersonalSyncActor.start(runId); require(Regex("[a-f0-9]{64}").matches(source)); PhoneContentScope.validate(scope) }

    fun current(source: String, scope: JsonObject, nowMs: Long, elapsedMs: Long) {
        if (invalid || this.source != source || this.scope != scope || nowMs >= wallDeadline || elapsedMs >= monotonicDeadline) {
            invalid = true
            error("actor_target_origin_changed")
        }
    }

    private fun body(wire: JsonObject, nowMs: Long): JsonObject {
        TelefonNachrichten.validateHeader(wire, nowMs)
        require(wire.string("kind") == PersonalSyncActor.DATA_KIND && wire.long("expires_ms") > nowMs &&
            wire.long("expires_ms") - wire.long("created_ms") <= 86_400_000)
        val (kind, body) = PersonalSyncActor.unwrap(wire.getValue("body").jsonObject)
        require(kind == "personal_sync.deletion_proposals" && body.string("run_id") == runId)
        require(body.getValue("proposals").jsonArray.all { it.jsonObject.string("kind") in setOf("note", "task", "attachment") })
        return body
    }

    fun capture(wire: JsonObject, source: String, scope: JsonObject, nowMs: Long, elapsedMs: Long) {
        current(source, scope, nowMs, elapsedMs)
        val body = body(wire, nowMs)
        val clear = TelefonKanonisch.bytes(wire)
        require(clear.size <= 256 * 1024)
        val id = wire.string("message_id")
        frames[id]?.let {
            val same = it.contentEquals(clear); clear.fill(0)
            if (!same) { invalid = true; error("actor_target_origin_frame_changed") }
            return // Exact retransmission never renews either deadline.
        }
        val count = body.getValue("proposals").jsonArray.size
        if (frames.size >= 256 || byteCount + clear.size > 1024 * 1024 || targetCount + count > 256) {
            clear.fill(0); invalid = true; error("actor_target_origin_capacity")
        }
        frames[id] = clear; byteCount += clear.size; targetCount += count
    }

    fun read(source: String, scope: JsonObject, nowMs: Long, elapsedMs: Long): List<JsonObject> {
        current(source, scope, nowMs, elapsedMs)
        val sequences = mutableMapOf<Int, Boolean>(); var batch: String? = null
        val proposals = mutableSetOf<String>(); val targets = mutableSetOf<Triple<String, String, String>>()
        val result = frames.values.map { clear ->
            val wire = Json.parseToJsonElement(clear.decodeToString()).jsonObject
            val body = body(wire, nowMs); val sequence = body.getValue("sequence").jsonPrimitive.int
            check(sequence !in sequences && (batch == null || batch == body.string("proposal_batch_id"))) { "actor_target_origin_group" }
            batch = body.string("proposal_batch_id"); sequences[sequence] = body.getValue("last").jsonPrimitive.boolean
            for (raw in body.getValue("proposals").jsonArray) {
                val item = raw.jsonObject
                check(proposals.add(item.string("proposal_id")) && targets.add(Triple(item.string("kind"), item.string("parent_id"), item.string("id")))) {
                    "actor_target_origin_group"
                }
            }
            sequence to wire
        }
        check(result.isNotEmpty() && sequences.keys.sorted() == (0 until sequences.size).toList() &&
            sequences.all { (index, last) -> last == (index == sequences.size - 1) }) { "actor_target_origin_incomplete" }
        return result.sortedBy { it.first }.map { it.second }
    }

    fun clear() { frames.values.forEach { it.fill(0) }; frames.clear(); invalid = true }
}
