package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull
import java.security.MessageDigest
import java.util.UUID
import kotlinx.serialization.json.buildJsonObject

@Serializable
data class PersonalSyncClock(val actor_id: String, val counter: Long)

@Serializable
data class PersonalSyncEntity(
    val clock: List<PersonalSyncClock> = emptyList(),
    val hash: String = "",
    val modified_ms: Long = 0,
    val conflict: Boolean = false,
    val state: String = "live",
    val peer_device_id: String = "",
    val acknowledged_by_peer: Boolean = false,
    val prior_hash: String = "",
    val deleted_ms: Long = 0,
    val label: String = "",
    val parent_id: String = "",
    val proposal_id: String = "",
    val status: String = "live"
)

@Serializable
data class PersonalSyncState(
    val format: Int = 1,
    val actor_id: String = "",
    val counter: Long = 0,
    val entities: Map<String, PersonalSyncEntity> = emptyMap(),
    val applied_batches: List<String> = emptyList(),
    val last_reports: List<String> = emptyList(),
    val peer_device_id: String = "",
    val restoration_requests: List<String> = emptyList(),
    val pending_proposals: List<PersonalDeletionProposal> = emptyList(),
    val applied_decisions: List<String> = emptyList(),
    val applied_decision_proofs: List<AppliedPersonalDecision> = emptyList(),
    val pending_decisions: List<PendingPersonalDecision> = emptyList(),
    val note_ids: Map<String, String> = emptyMap(),
    val note_aliases: Map<String, String> = emptyMap()
)

@Serializable
data class AppliedPersonalDecision(
    val proposal_id: String,
    val decision: String,
    val expected_clock: List<PersonalSyncClock>,
    val decision_id: String = ""
)

@Serializable
data class PendingPersonalDecision(
    val peer_device_id: String,
    val run_id: String,
    val decision_id: String,
    val proposal_id: String,
    val decision: String,
    val expected_clock: List<PersonalSyncClock>,
    val state: String = "pending"
)

@Serializable
data class PersonalDeletionProposal(
    val run_id: String,
    val proposal_id: String,
    val kind: String,
    val id: String,
    val parent_id: String = "",
    val clock: List<PersonalSyncClock>,
    val prior_hash: String,
    val deleted_ms: Long,
    val label: String = "",
    val source_device: String = ""
)

data class PersonalSyncRecord(
    val kind: String,
    val id: String,
    val clock: List<PersonalSyncClock>,
    val hash: String,
    val modifiedMs: Long,
    val value: JsonObject
)

data class PersonalSyncSnapshot(
    val records: List<PersonalSyncRecord>,
    val attachments: Map<String, PersonalSync.AttachmentSnapshot>
)

data class PersonalSyncResult(
    val bestand: Bestand,
    val conflicts: Int = 0,
    val received: Int = 0,
    val attachmentsOmitted: Int = 0
)

/** Personal data only. This file deliberately has no phone or tree dependencies. */
object PersonalSync {
    internal fun revokeDeletionConsent(state: PersonalSyncState, peerId: String?, kinds: Set<String>? = null): PersonalSyncState {
        if (peerId.isNullOrBlank()) return state
        val removed = state.pending_proposals.filter { it.source_device == peerId && (kinds == null || it.kind in kinds) }
            .mapTo(mutableSetOf()) { it.proposal_id }
        state.entities.forEach { (key, value) ->
            if (value.peer_device_id == peerId && (kinds == null || key.substringBefore('\u0000') in kinds) && value.proposal_id.isNotEmpty())
                removed += value.proposal_id
        }
        return state.copy(
            pending_proposals = state.pending_proposals.filterNot { it.source_device == peerId && (kinds == null || it.kind in kinds) },
            pending_decisions = state.pending_decisions.filterNot { it.peer_device_id == peerId && (kinds == null || it.proposal_id in removed) })
    }

    private val uuid4 = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

    private fun validNoteId(id: String) = id.isNotEmpty() && id == id.trim() && '\u0000' !in id && id.toByteArray(Charsets.UTF_8).size <= 160

    fun noteId(state: PersonalSyncState, value: String): String {
        var id = value
        val seen = mutableSetOf<String>()
        while (id in state.note_aliases) {
            val next = state.note_aliases.getValue(id)
            require(seen.add(id) && validNoteId(next) && compareUtf8(next, id) < 0) { "Invalid note identity mapping" }
            id = next
        }
        return id
    }

    fun noteWireId(state: PersonalSyncState, localId: String): String {
        val mapped = state.note_ids[localId]
        require(mapped == null || validNoteId(mapped)) { "Invalid note identity mapping" }
        return noteId(state, mapped ?: localId)
    }

    fun noteLocalId(input: Bestand, wireId: String): String {
        val canonical = noteId(input.personalSync, wireId)
        return input.notizen.firstOrNull { noteWireId(input.personalSync, it.id) == canonical }?.id
            ?: input.personalSync.note_ids.keys.firstOrNull { noteWireId(input.personalSync, it) == canonical } ?: canonical
    }

    private fun noteContent(value: JsonObject): JsonObject {
        val content = value.filterKeys { it !in setOf("created_ms", "modified_ms") }.toMutableMap()
        val title = (value["title"] as? JsonPrimitive)?.content
        if (title != null && (value["html"] as? JsonPrimitive)?.content == "" &&
            (value["attachments"] as? JsonArray).orEmpty().isEmpty()) {
            content["text"] = JsonPrimitive(NotizVorlagen.vergleichsText(title, (value["text"] as? JsonPrimitive)?.content.orEmpty()))
        }
        return JsonObject(content)
    }

    fun canonical(value: kotlinx.serialization.json.JsonElement): ByteArray {
        val encoded = Charsets.UTF_8.newEncoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
            .encode(java.nio.CharBuffer.wrap(canonicalText(value)))
        return ByteArray(encoded.remaining()).also { encoded.get(it) }
    }

    private fun canonicalText(value: kotlinx.serialization.json.JsonElement): String = when (value) {
        is JsonObject -> value.keys.sortedWith { a, b -> compareUtf8(a, b) }.joinToString(",", "{", "}") {
            canonicalText(JsonPrimitive(it)) + ":" + canonicalText(value.getValue(it))
        }
        is JsonArray -> value.joinToString(",", "[", "]", transform = ::canonicalText)
        is JsonPrimitive -> if (value.isString) {
            Charsets.UTF_8.newEncoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                .encode(java.nio.CharBuffer.wrap(value.content))
            value.toString()
        } else if (value == JsonNull || value.booleanOrNull != null) value.toString()
        else {
            require(Regex("-?(0|[1-9][0-9]*)").matches(value.content))
            (value.longOrNull ?: error("Invalid canonical integer")).toString()
        }
    }

    fun hash(value: JsonObject): String = MessageDigest.getInstance("SHA-256")
        .digest(canonical(value)).joinToString("") { "%02x".format(it) }

    fun recordsHash(records: List<PersonalSyncRecord>): String {
        val sorted = records.sortedWith { a, b -> compareUtf8(a.kind, b.kind).takeIf { it != 0 } ?: compareUtf8(a.id, b.id) }
        require(sorted == records && records.distinctBy { it.kind to it.id }.size == records.size)
        val wire = JsonArray(records.map { record -> buildJsonObject {
            put("kind", JsonPrimitive(record.kind)); put("id", JsonPrimitive(record.id)); put("state", JsonPrimitive("live"))
            put("clock", JsonArray(record.clock.map { buildJsonObject { put("actor_id", JsonPrimitive(it.actor_id)); put("counter", JsonPrimitive(it.counter)) } }))
            put("hash", JsonPrimitive(record.hash)); put("modified_ms", JsonPrimitive(record.modifiedMs)); put("value", record.value)
        } })
        return MessageDigest.getInstance("SHA-256").digest(canonical(wire)).joinToString("") { "%02x".format(it) }
    }

    data class AttachmentSnapshot(val descriptor: JsonObject, val bytes: ByteArray)

    fun attachmentDescriptor(value: Anhang): AttachmentSnapshot? {
        val content = AnhangPruefung.dataUrl(value.daten) ?: return null
        val id = value.id
        if (id.isEmpty() || id != id.trim() || id.toByteArray().size > 160 || '\u0000' in id) return null
        val name = value.name
        if (name.isEmpty() || name.toByteArray().size > 720 || name.any {
                it.code < 32 || it.code == 127 || it == '/' || it == '\\' }) return null
        val digest = MessageDigest.getInstance("SHA-256").digest(content.bytes).joinToString("") { "%02x".format(it) }
        return AttachmentSnapshot(buildJsonObject {
            put("attachment_id", JsonPrimitive(id)); put("name", JsonPrimitive(name))
            put("kind", JsonPrimitive(AnhangPruefung.arten.getValue(content.mime))); put("mime", JsonPrimitive(content.mime))
            put("size", JsonPrimitive(content.bytes.size)); put("sha256", JsonPrimitive(digest))
        }, content.bytes)
    }

    fun compare(left: List<PersonalSyncClock>, right: List<PersonalSyncClock>): String {
        validateClock(left); validateClock(right)
        val a = left.associate { it.actor_id to it.counter }
        val b = right.associate { it.actor_id to it.counter }
        val keys = a.keys + b.keys
        val greater = keys.any { (a[it] ?: 0) > (b[it] ?: 0) }
        val smaller = keys.any { (a[it] ?: 0) < (b[it] ?: 0) }
        return when { greater && smaller -> "concurrent"; greater -> "dominates"; smaller -> "dominated"; else -> "equal" }
    }

    fun merge(left: List<PersonalSyncClock>, right: List<PersonalSyncClock>): List<PersonalSyncClock> {
        validateClock(left); validateClock(right)
        return (left + right).groupBy { it.actor_id }.mapValues { it.value.maxOf(PersonalSyncClock::counter) }
            .entries.sortedWith { a, b -> compareUtf8(a.key, b.key) }
            .map { PersonalSyncClock(it.key, it.value) }.also { require(it.size <= 16) }
    }

    fun conflictId(kind: String, id: String, loserHash: String): String {
        val bytes = MessageDigest.getInstance("SHA-256")
            .digest("$kind\u0000$id\u0000$loserHash".toByteArray()).copyOf(16)
        bytes[6] = ((bytes[6].toInt() and 0x0f) or 0x40).toByte()
        bytes[8] = ((bytes[8].toInt() and 0x3f) or 0x80).toByte()
        return UUID(bytes.toLong(0), bytes.toLong(8)).toString()
    }

    fun proposalId(peerId: String, kind: String, id: String, parentId: String,
                   clock: List<PersonalSyncClock>, priorHash: String): String {
        require(uuid4.matches(peerId) && kind in setOf("note", "task", "notebook", "attachment"))
        require(id.isNotEmpty() && id == id.trim() && id.toByteArray().size <= 160 && '\u0000' !in id)
        require(parentId == parentId.trim() && parentId.toByteArray().size <= 160 && '\u0000' !in parentId)
        validateClock(clock)
        val material = JsonArray(listOf(JsonPrimitive(peerId), JsonPrimitive(kind), JsonPrimitive(id),
            JsonPrimitive(parentId), JsonArray(clock.map { buildJsonObject {
                put("actor_id", JsonPrimitive(it.actor_id)); put("counter", JsonPrimitive(it.counter))
            } }), JsonPrimitive(priorHash)))
        val bytes = MessageDigest.getInstance("SHA-256").digest("personal-deletion-v1\u0000".toByteArray() + canonical(material)).copyOf(16)
        bytes[6] = ((bytes[6].toInt() and 0x0f) or 0x40).toByte(); bytes[8] = ((bytes[8].toInt() and 0x3f) or 0x80).toByte()
        return UUID(bytes.toLong(0), bytes.toLong(8)).toString()
    }

    fun acknowledge(input: Bestand, peerId: String): Bestand {
        require(uuid4.matches(peerId))
        val samePeer = input.personalSync.peer_device_id == peerId
        val entities = input.personalSync.entities.mapValues { (_, value) ->
            if (value.state == "live") value.copy(peer_device_id = peerId, acknowledged_by_peer = true) else value
        }
        return input.copy(personalSync = input.personalSync.copy(peer_device_id = peerId,
            entities = entities, restoration_requests = if (samePeer) input.personalSync.restoration_requests else emptyList()))
    }

    fun proposals(input: Bestand, peerId: String): List<PersonalDeletionProposal> =
        input.personalSync.entities.mapNotNull { (key, meta) ->
            if (meta.state != "deleted" || meta.peer_device_id != peerId || meta.status == "resolved" ||
                meta.proposal_id.isBlank()) return@mapNotNull null
            val parts = key.split('\u0000')
            PersonalDeletionProposal("", meta.proposal_id, parts[0], parts.last(),
                if (parts[0] == "attachment") parts.getOrElse(1) { "" } else "", meta.clock,
                meta.prior_hash, meta.deleted_ms, meta.label)
        }.sortedWith { a, b -> compareUtf8(a.proposal_id, b.proposal_id) }

    fun stageProposals(input: Bestand, runId: String, source: String,
                       proposals: List<PersonalDeletionProposal>): Bestand {
        val existing = input.personalSync.pending_proposals.associateBy { it.proposal_id }.toMutableMap()
        proposals.forEach { existing.putIfAbsent(it.proposal_id, it.copy(run_id = runId, source_device = source)) }
        return input.copy(personalSync = input.personalSync.copy(
            pending_proposals = existing.values.sortedWith { a, b -> compareUtf8(a.proposal_id, b.proposal_id) }))
    }

    internal fun applyDeletionDecisions(input: Bestand,
        decisions: List<AppliedPersonalDecision>): Pair<Bestand, String> {
        val decisionIds = decisions.map { it.decision_id }.filter { it.isNotEmpty() }.distinct()
        if (decisionIds.size > 1) return input to "conflict"
        if (decisionIds.size == 1) {
            val previous = input.personalSync.applied_decision_proofs.filter { it.decision_id == decisionIds.single() }
            if (previous.isNotEmpty()) return if (previous == decisions) input to "applied" else input to "conflict"
        }
        var next = input
        for (decision in decisions) {
            val proof = next.personalSync.applied_decision_proofs.firstOrNull {
                it.proposal_id == decision.proposal_id
            }
            if (proof != null) {
                if (proof.decision != decision.decision || proof.expected_clock != decision.expected_clock)
                    return input to "conflict"
                if (decision.decision_id.isNotEmpty()) next = next.copy(personalSync = next.personalSync.copy(
                    applied_decision_proofs = next.personalSync.applied_decision_proofs + decision))
                continue
            }
            if (next.personalSync.applied_decisions.any { it.substringBefore(':') == decision.proposal_id })
                return input to "conflict"
            val found = next.personalSync.entities.entries.firstOrNull {
                it.value.proposal_id == decision.proposal_id
            } ?: return input to "conflict"
            if (found.value.clock != decision.expected_clock) return input to "conflict"
            if (decision.decision == "restore") {
                val entityId = found.key.substringAfterLast('\u0000')
                val trash = next.papierkorb.lastOrNull { item -> item.art == found.key.substringBefore('\u0000') && when (item.art) {
                    "note" -> item.notiz?.id == noteLocalId(next, entityId)
                    "task" -> item.aufgabe?.id == entityId
                    "notebook" -> item.notizbuch?.id == entityId
                    "attachment" -> item.anhang?.id == entityId && item.parent_id == noteLocalId(next, found.value.parent_id)
                    else -> false
                } } ?: return input to "restore_unavailable"
                next = PapierkorbLogik.wiederherstellen(next, trash.id)
                    ?: return input to "restore_unavailable"
            } else {
                if (decision.decision != "delete") return input to "conflict"
                next = next.copy(personalSync = next.personalSync.copy(entities =
                    next.personalSync.entities + (found.key to found.value.copy(status = "resolved"))))
            }
            next = next.copy(personalSync = next.personalSync.copy(
                applied_decisions = (next.personalSync.applied_decisions +
                    "${decision.proposal_id}:${decision.decision}"),
                applied_decision_proofs = next.personalSync.applied_decision_proofs + decision))
        }
        return next to "applied"
    }

    private fun ByteArray.toLong(offset: Int): Long {
        var result = 0L
        repeat(8) { result = (result shl 8) or (this[offset + it].toLong() and 255) }
        return result
    }

    private fun validateClock(clock: List<PersonalSyncClock>) {
        require(clock.size in 1..16)
        require(clock == clock.sortedWith { a, b -> compareUtf8(a.actor_id, b.actor_id) })
        require(clock.distinctBy { it.actor_id }.size == clock.size)
        require(clock.all { uuid4.matches(it.actor_id) && it.counter in 1..9_007_199_254_740_991L })
    }

    fun reconcile(input: Bestand, modules: Set<String>, format: Int = 1,
                  peerId: String = input.personalSync.peer_device_id,
                  nowMs: Long = System.currentTimeMillis()): Pair<Bestand, List<PersonalSyncRecord>> {
        require(format in 1..3)
        var state = input.personalSync
        val actor = state.actor_id.takeIf(uuid4::matches) ?: UUID.randomUUID().toString()
        var counter = state.counter.coerceAtLeast(0)
        val entities = state.entities.toMutableMap()
        val projected = projections(input, modules, format)
        val projectedAttachments = if (format >= 2 && "notes" in modules) input.notizen
            .filter(::ownNote).flatMap { note -> note.anhaenge.mapNotNull { attachment ->
                attachmentDescriptor(attachment)?.let { snapshot ->
                    "attachment\u0000${noteWireId(state, note.id)}\u0000${attachment.id}" to Triple(note, attachment, snapshot)
                }
            } }.toMap() else emptyMap()
        if (peerId.isNotEmpty() && peerId != state.peer_device_id) {
            // A replacement phone receives an additive baseline. Old tombstones remain archived but cannot target it.
            state = state.copy(peer_device_id = peerId, restoration_requests = emptyList())
            entities.replaceAll { _, value -> value.copy(acknowledged_by_peer = false) }
        }
        val eligibleKinds = buildSet { if ("notes" in modules) addAll(listOf("note", "notebook")); if ("tasks" in modules) add("task") }
        val present = buildSet {
            input.notizen.forEach { note ->
                add("note\u0000${noteWireId(state, note.id)}")
                note.anhaenge.forEach { add("attachment\u0000${noteWireId(state, note.id)}\u0000${it.id}") }
            }
            input.aufgaben.forEach { add("task\u0000${it.id}") }
            input.notizbuecher.forEach { add("notebook\u0000${it.id}") }
        }
        for ((key, old) in entities.toMap()) {
            val kind = key.substringBefore('\u0000')
            val attachmentGone = kind == "attachment" && format >= 2 && "notes" in modules && key !in projectedAttachments
            val parentGone = kind == "attachment" && key.split('\u0000').getOrElse(1) { "" }.let { parent ->
                "note\u0000$parent" !in projected
            }
            if ((kind in eligibleKinds && key !in projected || attachmentGone) && key !in present && !parentGone &&
                old.state == "live" && old.acknowledged_by_peer && old.peer_device_id == peerId) {
                counter++
                val clock = mergeOptional(old.clock, PersonalSyncClock(actor, counter))
                val parts = key.split('\u0000'); val id = parts.last()
                val parent = if (kind == "attachment") parts.getOrElse(1) { "" } else ""
                entities[key] = old.copy(clock = clock, state = "deleted", prior_hash = old.hash,
                    deleted_ms = nowMs, proposal_id = proposalId(peerId, kind, id, parent, clock, old.hash),
                    status = "local_pending", hash = "", acknowledged_by_peer = false)
            }
        }
        for ((key, triple) in projectedAttachments) {
            val descriptor = triple.third.descriptor
            val digest = hash(descriptor)
            val old = entities[key]
            if (old?.state == "deleted") continue
            if (old == null || old.hash != digest) {
                counter++
                entities[key] = PersonalSyncEntity(mergeOptional(old?.clock.orEmpty(),
                    PersonalSyncClock(actor, counter)), digest, triple.first.geaendert,
                    label = triple.second.name, parent_id = noteWireId(state, triple.first.id))
            }
        }
        for ((key, value) in projected) {
            val digest = hash(value)
            val old = entities[key]
            if (old?.state == "deleted") continue
            if (old == null || old.hash != digest) {
                counter++
                val clock = mergeOptional(old?.clock.orEmpty(), PersonalSyncClock(actor, counter))
                val label = when (key.substringBefore('\u0000')) {
                    "notebook" -> value.text("name")
                    else -> value.text("title")
                }.take(120)
                entities[key] = PersonalSyncEntity(clock, digest, value.longValue("modified_ms"), label = label)
            }
        }
        state = state.copy(format = format, actor_id = actor, counter = counter, entities = entities)
        val records = projected.mapNotNull { (key, value) ->
            val meta = entities[key]?.takeIf { it.state == "live" } ?: return@mapNotNull null
            val split = key.split('\u0000', limit = 2)
            PersonalSyncRecord(split[0], split[1], meta.clock, meta.hash, meta.modified_ms, value)
        }.sortedWith { a, b -> compareUtf8(a.kind, b.kind).takeIf { it != 0 } ?: compareUtf8(a.id, b.id) }
        return input.copy(personalSync = state) to records
    }

    private fun mergeOptional(clock: List<PersonalSyncClock>, item: PersonalSyncClock): List<PersonalSyncClock> =
        (clock + item).groupBy { it.actor_id }.mapValues { it.value.maxOf(PersonalSyncClock::counter) }
            .entries.sortedWith { a, b -> compareUtf8(a.key, b.key) }.map { PersonalSyncClock(it.key, it.value) }

    private fun projections(input: Bestand, modules: Set<String>, format: Int): Map<String, JsonObject> {
        val result = linkedMapOf<String, JsonObject>()
        if ("notes" in modules) {
            input.notizbuecher.forEach { result["notebook\u0000${it.id}"] = notebookValue(it) }
            input.notizen.filter(::ownNote).forEach { result["note\u0000${noteWireId(input.personalSync, it.id)}"] = noteValue(it, format) }
        }
        if ("tasks" in modules) AufgabenHierarchie.normalisieren(input.aufgaben.filter {
            it.vonZweig.isBlank() && it.fremdId.isBlank() && it.delegiertAn.isBlank() && it.herkunft.isBlank()
        }).forEach {
            result["task\u0000${it.id}"] = taskValue(it, format)
        }
        return result
    }

    fun ownNote(note: Notiz) = note.baumQuelle.isBlank() || note.persoenlichVerknuepft

    /** Pure operation inside a real sync transaction; never run during profile load or preview. */
    internal fun compactNotes(input: Bestand): Bestand {
        if (input.personalSync.pending_decisions.isNotEmpty()) return input
        var state = input.personalSync
        val replacements = mutableMapOf<String, Notiz>()
        val removed = mutableSetOf<String>()
        val groups = input.notizen.filter { note -> validNoteId(note.id) &&
            (noteValue(note, 2)["attachments"] as? JsonArray).orEmpty().size == note.anhaenge.size
        }.groupBy { noteContent(noteValue(it, 2)) }
        for (group in groups.values) {
            if (group.size < 2 || group.map { it.id }.distinct().size != group.size ||
                group.map { it.einfuhrSchluessel }.filter { it.isNotBlank() }.distinct().size > 1) continue
            val wires = group.mapTo(mutableSetOf()) { noteWireId(state, it.id) }
            if (wires.any { !validNoteId(it) } || input.notizen.any { it !in group && noteWireId(state, it.id) in wires }) continue
            fun affected(key: String): Boolean {
                val parts = key.split('\u0000')
                return parts.size >= 2 && parts[0] in setOf("note", "attachment") && noteId(state, parts[1]) in wires
            }
            val metadata = state.entities.filterKeys(::affected)
            val attachmentIds = group.first().anhaenge.map { it.id }.toSet()
            if (metadata.any { (key, meta) -> meta.state == "deleted" || meta.conflict ||
                    key.startsWith("attachment\u0000") && key.substringAfterLast('\u0000') !in attachmentIds } ||
                state.restoration_requests.any(::affected) || state.pending_proposals.any {
                    affected(it.kind + "\u0000" + (if (it.kind == "attachment") it.parent_id + "\u0000" else "") + it.id)
                }) continue
            val keeper = group.first()
            val canonical = wires.minWithOrNull(::compareUtf8)!!
            val nextMeta = linkedMapOf<String, PersonalSyncEntity>()
            var safe = true
            for ((key, meta) in metadata) {
                val parts = key.split('\u0000')
                val target = parts[0] + "\u0000" + canonical +
                    (if (parts[0] == "attachment") "\u0000" + parts[2] else "")
                val old = nextMeta[target]
                val clock = runCatching {
                    if (old == null) { validateClock(meta.clock); meta.clock } else merge(old.clock, meta.clock)
                }.getOrNull()
                if (clock == null || old != null && parts[0] == "attachment" && old.hash != meta.hash) { safe = false; break }
                nextMeta[target] = (old ?: meta).copy(clock = clock, acknowledged_by_peer = false,
                    parent_id = if (parts[0] == "attachment") canonical else meta.parent_id)
            }
            if (!safe) continue
            val shared = group.filter { it.baumFreigabe != null }
            val sources = linkedMapOf<Pair<String, String>, NotizQuelle>()
            for (note in shared) {
                val share = note.baumFreigabe!!
                val known = share.quellen + share.partner.filter { partner ->
                    share.quellen.none { it.partner == partner }
                }.map { NotizQuelle(it, share.id, note.baumVersion, note.baumQuelle) }
                for (source in known) {
                    val key = source.partner to source.id
                    val previous = sources[key]
                    val current = previous == null || source.version > previous.version ||
                        source.version == previous.version && source.quelle > previous.quelle
                    val baseline = if (source.stand == note.baumInhaltVersion && (previous == null || previous.stand >= 0))
                        keeper.baumInhaltVersion else -1L
                    sources[key] = (if (current) source else previous!!).copy(stand = baseline)
                }
            }
            val partners = shared.flatMap { it.baumFreigabe!!.partner }.distinct()
            val share = shared.firstOrNull()?.baumFreigabe?.copy(partner = partners, quellen = sources.values.toList(),
                anhangPartner = partners.filter { partner -> shared.filter { partner in it.baumFreigabe!!.partner }
                    .all { partner in it.baumFreigabe!!.anhangPartner } })
            replacements[keeper.id] = keeper.copy(baumFreigabe = share,
                baumVersion = group.maxOf { it.baumVersion }, baumGeaendert = group.maxOf { it.baumGeaendert },
                baumQuelle = keeper.baumQuelle.ifBlank { shared.firstOrNull()?.baumQuelle.orEmpty() },
                persoenlichVerknuepft = group.any(::ownNote),
                einfuhrSchluessel = keeper.einfuhrSchluessel.ifBlank { group.firstOrNull { it.einfuhrSchluessel.isNotBlank() }?.einfuhrSchluessel.orEmpty() })
            state = state.copy(note_ids = state.note_ids + group.associate { it.id to canonical },
                note_aliases = state.note_aliases + wires.filter { it != canonical }.associateWith { canonical },
                entities = (state.entities - metadata.keys) + nextMeta)
            removed += group.drop(1).map { it.id }
        }
        return if (removed.isEmpty()) input else input.copy(personalSync = state,
            notizen = input.notizen.filterNot { it.id in removed }.map { replacements[it.id] ?: it })
    }

    fun apply(original: Bestand, records: List<PersonalSyncRecord>,
              attachments: Map<String, Anhang> = emptyMap(),
              mergeNotes: Boolean = records.any { it.kind in setOf("note", "notebook") }): PersonalSyncResult {
        val compacted = if (mergeNotes) compactNotes(original) else original
        val input = if (compacted == original) original else reconcile(compacted, setOf("notes"),
            original.personalSync.format, original.personalSync.peer_device_id).first
        var notes = input.notizen
        var tasks = input.aufgaben
        var books = input.notizbuecher
        var identities = input.personalSync
        val entities = input.personalSync.entities.toMutableMap()
        var conflicts = 0
        var received = 0
        var omitted = 0
        fun localId(wire: String) = noteLocalId(input.copy(notizen = notes, personalSync = identities), wire)
        for (incoming in records.sortedWith { a, b -> compareUtf8(a.kind, b.kind).takeIf { it != 0 } ?: compareUtf8(a.id, b.id) }) {
            var remote = incoming
            require(remote.kind in setOf("note", "task", "notebook") && remote.id.isNotEmpty() && remote.id == remote.id.trim() &&
                remote.id.toByteArray(Charsets.UTF_8).size <= 160 && '\u0000' !in remote.id)
            validateClock(remote.clock)
            require(hash(remote.value) == remote.hash && remote.modifiedMs == remote.value.longValue("modified_ms"))
            if (remote.kind == "note" && notes.any { !ownNote(it) &&
                (it.id == remote.id || noteWireId(identities, it.id) == noteId(identities, remote.id)) }) {
                conflicts++; continue
            }
            if (remote.kind == "note") {
                var id = noteId(identities, remote.id)
                if (entities["note\u0000$id"] == null && entities.keys.none { it.startsWith("attachment\u0000$id\u0000") }) {
                    val format = if ("attachments" in remote.value) 2 else 1
                    val candidate = notes.filter { note ->
                        val meta = entities["note\u0000${noteWireId(identities, note.id)}"]
                        val wire = noteWireId(identities, note.id)
                        validNoteId(wire) && (note.baumFreigabe == null || note.persoenlichVerknuepft) && ownNote(note) &&
                            note.anhaenge.size == (remote.value["attachments"] as? JsonArray).orEmpty().size &&
                            meta != null && meta.state == "live" && !meta.conflict && noteContent(noteValue(note, format)) == noteContent(remote.value) &&
                            entities.none { (key, value) -> key.startsWith("attachment\u0000$wire\u0000") && value.state == "deleted" } &&
                            identities.pending_proposals.none { it.kind == "note" && it.id == wire || it.kind == "attachment" && it.parent_id == wire } &&
                            identities.restoration_requests.none { it == "note\u0000$wire" || it.startsWith("attachment\u0000$wire\u0000") } &&
                            identities.pending_decisions.isEmpty()
                    }.minWithOrNull { a, b -> compareUtf8(noteWireId(identities, a.id), noteWireId(identities, b.id)) }
                    if (candidate != null) {
                        val previous = noteWireId(identities, candidate.id)
                        val canonical = if (compareUtf8(previous, id) <= 0) previous else id
                        val aliases = identities.note_aliases.toMutableMap()
                        if (previous != canonical) {
                            aliases[previous] = canonical
                            entities["note\u0000$canonical"] = entities.getValue("note\u0000$previous").copy(acknowledged_by_peer = false)
                            entities.remove("note\u0000$previous")
                            val prefix = "attachment\u0000$previous\u0000"
                            for ((childKey, meta) in entities.toMap()) if (childKey.startsWith(prefix)) {
                                entities["attachment\u0000$canonical\u0000${childKey.removePrefix(prefix)}"] =
                                    meta.copy(parent_id = canonical, acknowledged_by_peer = false)
                                entities.remove(childKey)
                            }
                        }
                        if (id != canonical) aliases[id] = canonical
                        identities = identities.copy(note_ids = identities.note_ids + (candidate.id to canonical), note_aliases = aliases)
                        id = canonical
                    }
                }
                remote = remote.copy(id = id)
            }
            val key = "${remote.kind}\u0000${remote.id}"
            val localNoteId = if (remote.kind == "note") localId(remote.id) else remote.id
            if (remote.kind == "note" && notes.any { it.id == localNoteId && !ownNote(it) } ||
                remote.kind == "task" && tasks.any { it.id == remote.id &&
                    (it.vonZweig.isNotBlank() || it.fremdId.isNotBlank() || it.delegiertAn.isNotBlank() || it.herkunft.isNotBlank()) }) {
                conflicts++
                continue
            }
            val localMeta = entities[key]
            if (localMeta?.state == "deleted") {
                // Stale records are restoration candidates only. They never recreate deleted content.
                continue
            }
            if (localMeta == null) {
                require(when (remote.kind) {
                    "note" -> notes.none { it.id == localNoteId }
                    "task" -> tasks.none { it.id == remote.id }
                    else -> books.none { it.id == remote.id }
                }) { "Existing personal object requires reconciliation" }
                when (remote.kind) {
                    "note" -> notes = notes + remoteNote(remote.copy(id = localNoteId), null, attachments)
                    "task" -> tasks = tasks + remoteTask(remote, null)
                    else -> books = books + remoteBook(remote)
                }
                entities[key] = PersonalSyncEntity(remote.clock, remote.hash, remote.modifiedMs)
                received++
                continue
            }
            when (compare(localMeta.clock, remote.clock)) {
                "dominates" -> Unit
                "equal" -> require(localMeta.hash == remote.hash)
                "dominated" -> {
                    when (remote.kind) {
                        "note" -> { val id = localId(remote.id); val old = notes.firstOrNull { it.id == id }
                            notes = notes.filterNot { it.id == id } + remoteNote(remote.copy(id = id), old, attachments) }
                        "task" -> { val old = tasks.firstOrNull { it.id == remote.id }; tasks = tasks.filterNot { it.id == remote.id } + remoteTask(remote, old) }
                        else -> books = books.filterNot { it.id == remote.id } + remoteBook(remote)
                    }
                    entities[key] = PersonalSyncEntity(remote.clock, remote.hash, remote.modifiedMs); received++
                }
                else -> {
                    val merged = merge(localMeta.clock, remote.clock)
                    if (localMeta.hash == remote.hash) {
                        entities[key] = localMeta.copy(clock = merged,
                            modified_ms = maxOf(localMeta.modified_ms, remote.modifiedMs), conflict = false)
                        continue
                    }
                    val remoteWins = remote.hash < localMeta.hash
                    if (remote.kind == "notebook") {
                        val local = books.firstOrNull { it.id == remote.id }
                        if (local != null && noteContent(notebookValue(local)) == noteContent(remote.value)) {
                            entities[key] = localMeta.copy(clock = merged,
                                hash = if (remoteWins) remote.hash else localMeta.hash,
                                modified_ms = if (remoteWins) remote.modifiedMs else localMeta.modified_ms, conflict = false)
                            continue
                        }
                    }
                    if (remote.kind == "note") {
                        val id = localId(remote.id)
                        val local = notes.firstOrNull { it.id == id }
                        val format = if ("attachments" in remote.value) 2 else 1
                        if (local != null && noteContent(noteValue(local, format)) == noteContent(remote.value)) {
                            // Keep wire hashes and clocks exact; only the conflict
                            // decision ignores timestamps and legacy template paths. Preserve local
                            // attachments not represented by this wire value.
                            if (remoteWins) notes = notes.filterNot { it.id == id } +
                                remoteNote(remote.copy(id = id), local, attachments, additive = true)
                            entities[key] = localMeta.copy(clock = merged,
                                hash = if (remoteWins) remote.hash else localMeta.hash,
                                modified_ms = if (remoteWins) remote.modifiedMs else localMeta.modified_ms, conflict = false)
                            continue
                        }
                    }
                    val loserHash = if (remoteWins) localMeta.hash else remote.hash
                    val conflictId = conflictId(remote.kind, remote.id, loserHash)
                    val conflictKey = "${remote.kind}\u0000$conflictId"
                    if (remote.kind == "note") {
                        val id = localId(remote.id)
                        val local = notes.firstOrNull { it.id == id }
                        if (remoteWins) {
                            if (local != null && notes.none { it.id == conflictId }) notes = notes + local.copy(id = conflictId,
                                baumFreigabe = null, baumQuelle = "", baumVersion = 0, baumGeaendert = 0,
                                baumInhaltVersion = 0, persoenlichVerknuepft = false)
                            notes = notes.filterNot { it.id == id } + remoteNote(remote.copy(id = id), local, attachments, additive = false)
                        } else if (notes.none { it.id == conflictId }) notes = notes + remoteNote(remote.copy(id = conflictId), null, attachments, additive = false)
                    } else if (remote.kind == "task") {
                        val local = tasks.firstOrNull { it.id == remote.id }
                        if (remoteWins) {
                            if (local != null && tasks.none { it.id == conflictId }) tasks = tasks + local.copy(id = conflictId,
                                uid = AufgabenHierarchie.stabileUid(conflictId), elternUid = "")
                            tasks = tasks.filterNot { it.id == remote.id } + remoteTask(remote, local)
                        } else if (tasks.none { it.id == conflictId }) tasks = tasks + remoteTask(remote.copy(id = conflictId), null).copy(
                            uid = AufgabenHierarchie.stabileUid(conflictId), elternUid = "")
                    } else {
                        val local = books.firstOrNull { it.id == remote.id }
                        if (remoteWins) {
                            if (local != null && books.none { it.id == conflictId }) books = books + local.copy(id = conflictId)
                            books = books.filterNot { it.id == remote.id } + remoteBook(remote)
                        } else if (books.none { it.id == conflictId }) books = books + remoteBook(remote.copy(id = conflictId))
                    }
                    entities[key] = PersonalSyncEntity(merged, if (remoteWins) remote.hash else localMeta.hash,
                        if (remoteWins) remote.modifiedMs else localMeta.modified_ms, true)
                    entities[conflictKey] = PersonalSyncEntity(merged, loserHash,
                        if (remoteWins) localMeta.modified_ms else remote.modifiedMs, true)
                    conflicts++; received++
                }
            }
        }
        val result = input.copy(notizen = notes,
            aufgaben = AufgabenHierarchie.normalisieren(tasks), notizbuecher = books,
            personalSync = identities.copy(entities = entities))
        val compactedResult = if (mergeNotes) compactNotes(result) else result
        val durable = if (compactedResult == result) result else reconcile(compactedResult, setOf("notes"),
            result.personalSync.format, result.personalSync.peer_device_id).first
        return PersonalSyncResult(durable, conflicts, received, omitted)
    }

    fun matchesCurrent(input: Bestand, proposal: PersonalDeletionProposal): Boolean {
        if (proposal.kind == "note" && noteId(input.personalSync, proposal.id) != proposal.id ||
            proposal.kind == "attachment" && noteId(input.personalSync, proposal.parent_id) != proposal.parent_id) return false
        if (proposal.kind == "attachment") {
            val parent = noteLocalId(input, proposal.parent_id)
            val note = input.notizen.firstOrNull { it.id == parent && ownNote(it) }
            val attachment = note?.anhaenge?.firstOrNull { it.id == proposal.id } ?: return false
            return attachmentDescriptor(attachment)?.let { hash(it.descriptor) == proposal.prior_hash } == true
        }
        val local = if (proposal.kind == "note") noteLocalId(input, proposal.id) else proposal.id
        return (1..3).any { format ->
            val value = when (proposal.kind) {
                "note" -> input.notizen.firstOrNull { it.id == local && ownNote(it) }
                    ?.let { noteValue(it, format) }
                "notebook" -> input.notizbuecher.firstOrNull { it.id == proposal.id }?.let(::notebookValue)
                "task" -> projections(input, setOf("tasks"), format)["task\u0000${proposal.id}"]
                else -> null
            }
            value?.let { hash(it) == proposal.prior_hash } == true
        }
    }

    private fun noteValue(value: Notiz, format: Int) = JsonObject(linkedMapOf(
        "title" to JsonPrimitive(value.titel), "text" to JsonPrimitive(value.text), "html" to JsonPrimitive(value.html),
        "notebook_id" to JsonPrimitive(value.notizbuchId), "symbol" to JsonPrimitive(value.symbol),
        "created_ms" to JsonPrimitive(value.angelegt.coerceAtLeast(0)), "modified_ms" to JsonPrimitive(value.geaendert.coerceAtLeast(0))) +
        if (format >= 2) mapOf("attachments" to JsonArray(value.anhaenge.mapNotNull(::attachmentDescriptor).take(64).map { it.descriptor })) else emptyMap())

    private fun taskValue(value: Aufgabe, format: Int) = JsonObject(linkedMapOf(
        "title" to JsonPrimitive(value.titel), "note" to JsonPrimitive(value.notiz), "due" to JsonPrimitive(value.faellig),
        "priority" to JsonPrimitive(value.prio), "completed" to JsonPrimitive(value.erledigt), "remind" to JsonPrimitive(value.erinnern),
        "lead_days" to JsonPrimitive(value.vorlaufTage), "reminder_minute" to JsonPrimitive(value.erinnerungsMinute),
        "created_ms" to JsonPrimitive(value.angelegt.coerceAtLeast(0)), "modified_ms" to JsonPrimitive(value.geaendert.coerceAtLeast(0))) +
        if (format == 3) mapOf("uid" to JsonPrimitive(value.uid),
            "parent_uid" to JsonPrimitive(value.elternUid), "order" to JsonPrimitive(value.reihenfolge.coerceAtLeast(0)))
        else emptyMap())

    private fun notebookValue(value: Notizbuch) = JsonObject(linkedMapOf(
        "name" to JsonPrimitive(value.name), "modified_ms" to JsonPrimitive(0)))

    private fun remoteNote(record: PersonalSyncRecord, old: Notiz?, attachments: Map<String, Anhang>,
                           additive: Boolean = true): Notiz {
        val declared = (record.value["attachments"] as? JsonArray).orEmpty().map {
            val descriptor = it as JsonObject
            attachments.getValue(descriptor.text("sha256")).copy(
                id = descriptor.text("attachment_id"), name = descriptor.text("name"),
                art = descriptor.text("kind"))
        }
        val merged = if (!additive) declared else mergeAttachments(old?.anhaenge.orEmpty(), declared)
        return io.gitlab.maik3531.magnolienotes.baum.NotizQuellen.lokaleAenderung(old, (old ?: Notiz(record.id)).copy(
            id = record.id, titel = record.value.text("title"), text = record.value.text("text"), html = record.value.text("html"),
            notizbuchId = record.value.text("notebook_id"), symbol = record.value.text("symbol"),
            angelegt = record.value.longValue("created_ms"), geaendert = record.modifiedMs, anhaenge = merged))
    }

    private fun mergeAttachments(local: List<Anhang>, remote: List<Anhang>): List<Anhang> {
        val result = local.toMutableList()
        for (item in remote) {
            val sameId = result.indexOfFirst { it.id == item.id }
            if (sameId < 0) result += item
            else if (result[sameId].daten == item.daten) result[sameId] = item
            else {
                val digest = MessageDigest.getInstance("SHA-256")
                    .digest((item.id + "\u0000" + item.daten).toByteArray()).joinToString("") { "%02x".format(it) }
                result += item.copy(id = conflictId("attachment", item.id, digest))
            }
        }
        return result.distinctBy { it.id to it.daten }
    }

    private fun remoteTask(record: PersonalSyncRecord, old: Aufgabe?) = (old ?: Aufgabe(record.id)).copy(
        id = record.id, titel = record.value.text("title"), notiz = record.value.text("note"), faellig = record.value.text("due"),
        prio = record.value.longValue("priority").toInt(), erledigt = record.value.bool("completed"),
        erinnern = record.value.bool("remind"), vorlaufTage = record.value.longValue("lead_days").toInt(),
        erinnerungsMinute = record.value.longValue("reminder_minute").toInt(), angelegt = record.value.longValue("created_ms"),
        geaendert = record.modifiedMs,
        uid = record.value.optionalText("uid") ?: old?.uid.orEmpty(),
        elternUid = record.value.optionalText("parent_uid") ?: old?.elternUid.orEmpty(),
        reihenfolge = record.value.optionalLong("order")?.coerceAtMost(Int.MAX_VALUE.toLong())?.toInt()
            ?: old?.reihenfolge ?: 0)

    private fun remoteBook(record: PersonalSyncRecord) = Notizbuch(record.id, record.value.text("name"))
    private fun JsonObject.text(name: String) = (getValue(name) as JsonPrimitive).content
    private fun JsonObject.longValue(name: String) = (getValue(name) as JsonPrimitive).content.toLong()
    private fun JsonObject.bool(name: String) = (getValue(name) as JsonPrimitive).content.toBooleanStrict()
    private fun JsonObject.optionalText(name: String) = (get(name) as? JsonPrimitive)?.content
    private fun JsonObject.optionalLong(name: String) = (get(name) as? JsonPrimitive)?.content?.toLong()

    internal fun compareUtf8(left: String, right: String): Int {
        val a = left.toByteArray(Charsets.UTF_8); val b = right.toByteArray(Charsets.UTF_8)
        for (index in 0 until minOf(a.size, b.size)) {
            val difference = (a[index].toInt() and 255) - (b[index].toInt() and 255)
            if (difference != 0) return difference
        }
        return a.size - b.size
    }
}
