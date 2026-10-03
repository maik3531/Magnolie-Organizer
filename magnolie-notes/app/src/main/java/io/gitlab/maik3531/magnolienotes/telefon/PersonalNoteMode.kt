package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncState
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncClock
import java.util.UUID

/** Authenticated, peer-scoped note direction; record/batch schemas remain V1–V3. */
object PersonalNoteMode {
    const val VERSION = 5
    const val KIND = "personal_sync.note_settings"
    const val TWO_WAY = "two_way"
    const val IMPORT = "phone_import"
    private const val MAX_REVISION = 9_007_199_254_740_991L

    fun validate(body: JsonObject) {
        TelefonNachrichten.exact(body, setOf("format", "mode", "revision", "epoch", "peer_epoch"))
        if (body.long("format") != VERSION.toLong() || body.string("mode") !in setOf(TWO_WAY, IMPORT) ||
            body.long("revision") !in 1..MAX_REVISION) throw TelefonProtokollFehler("Ungültige Notizrichtung.")
        TelefonNachrichten.uuid4(body.string("epoch"))
        if (body.string("peer_epoch").isNotEmpty()) TelefonNachrichten.uuid4(body.string("peer_epoch"))
    }

    fun create(mode: String = TWO_WAY, revision: Long = 1, peerEpoch: String = ""): JsonObject = buildJsonObject {
        put("format", JsonPrimitive(VERSION)); put("mode", JsonPrimitive(mode)); put("revision", JsonPrimitive(revision))
        put("epoch", JsonPrimitive(UUID.randomUUID().toString())); put("peer_epoch", JsonPrimitive(peerEpoch))
    }.also(::validate)

    fun accept(current: JsonObject?, incoming: JsonObject): JsonObject {
        validate(incoming)
        if (current != null) {
            validate(current)
            val revision = incoming.long("revision"); val old = current.long("revision")
            if (revision < old || revision == old && JsonObject(incoming - "peer_epoch") != JsonObject(current - "peer_epoch") ||
                revision > old && incoming.string("epoch") == current.string("epoch"))
                throw TelefonProtokollFehler("Veraltete Notizrichtung.")
        }
        return incoming
    }

    fun echo(local: JsonObject, remote: JsonObject?): JsonObject {
        validate(local); remote?.let(::validate)
        return JsonObject(local + ("peer_epoch" to JsonPrimitive(remote?.string("epoch").orEmpty())))
    }

    fun importing(local: JsonObject?, remote: JsonObject?): Boolean {
        val values = listOfNotNull(local, remote)
        values.forEach(::validate)
        return values.any { it.string("mode") == IMPORT }
    }

    fun ready(local: JsonObject?, remote: JsonObject?, receivedOnConnection: Boolean, sentOnConnection: Boolean): Boolean {
        if (!receivedOnConnection || !sentOnConnection || local == null || remote == null) return false
        return runCatching { validate(local); validate(remote)
            local.string("peer_epoch") == remote.string("epoch") && remote.string("peer_epoch") == local.string("epoch")
        }.getOrDefault(false)
    }

    fun samePolicy(a: JsonObject?, b: JsonObject?): Boolean = a != null && b != null &&
        JsonObject(a - "peer_epoch") == JsonObject(b - "peer_epoch")

    fun decisionKinds(state: PersonalSyncState, peerId: String, body: JsonObject, outgoing: Boolean): List<String>? {
        val decisions = body["decisions"] as? JsonArray ?: return null
        return decisions.map { entry ->
            val decision = entry as? JsonObject ?: return null
            val id = (decision["proposal_id"] as? JsonPrimitive)?.content ?: return null
            val clock = runCatching { TelefonKanonisch.json.decodeFromJsonElement<List<PersonalSyncClock>>(
                decision["expected_clock"] ?: return null) }.getOrNull() ?: return null
            val kinds = if (outgoing) {
                state.pending_proposals.filter { it.source_device == peerId && it.proposal_id == id && it.clock == clock }.map { it.kind } +
                    state.pending_decisions.filter { it.peer_device_id == peerId && it.proposal_id == id && it.expected_clock == clock }.map { it.kind }
            } else state.entities.filterValues { it.peer_device_id == peerId && it.proposal_id == id && it.clock == clock }
                .keys.map { it.substringBefore('\u0000') }
            kinds.filter(String::isNotEmpty).distinct().singleOrNull() ?: return null
        }
    }

    fun usesNotes(kind: String, body: JsonObject, decisionKinds: List<String>? = null): Boolean = when (kind) {
        "personal_sync.batch" -> (body["records"] as? JsonArray).orEmpty().any {
            ((it as? JsonObject)?.get("kind") as? JsonPrimitive)?.content in setOf("note", "notebook") }
        "personal_sync.request" -> (body["modules"] as? JsonArray).orEmpty().any { it == JsonPrimitive("notes") }
        "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result" -> true
        "personal_sync.deletion_proposals" -> (body["proposals"] as? JsonArray).orEmpty().any {
            ((it as? JsonObject)?.get("kind") as? JsonPrimitive)?.content != "task" }
        "personal_sync.deletion_decision" -> decisionKinds == null || decisionKinds.any { it != "task" }
        "personal_sync.report" -> listOf("sent", "received").any { direction ->
            val counts = body[direction] as? JsonObject
            listOf("notes", "notebooks").any { ((counts?.get(it) as? JsonPrimitive)?.content?.toLongOrNull() ?: 0) > 0 }
        }
        else -> false
    }

    fun allowed(role: String, outgoing: Boolean, kind: String, body: JsonObject, importing: Boolean,
                decisionKinds: List<String>? = null): Boolean {
        require(role in setOf("phone", "desktop"))
        if (!importing || kind == KIND || kind == "personal_sync.settings") return true
        val phoneToDesktop = if (outgoing) role == "phone" else role == "desktop"
        if (kind == "personal_sync.batch") {
            val records = body["records"] as? JsonArray ?: return false
            return phoneToDesktop || records.all { (it as? JsonObject)?.get("kind") == JsonPrimitive("task") }
        }
        if (kind == "personal_sync.attachment_chunk") return phoneToDesktop
        if (kind == "personal_sync.attachment_request") return !phoneToDesktop
        if (kind == "personal_sync.deletion_proposals") {
            val proposals = body["proposals"] as? JsonArray ?: return false
            return proposals.all { (it as? JsonObject)?.get("kind") == JsonPrimitive("task") }
        }
        if (kind == "personal_sync.deletion_decision") {
            val decisions = body["decisions"] as? JsonArray ?: return false
            return decisionKinds != null && decisionKinds.size == decisions.size && decisionKinds.all { it == "task" }
        }
        return true
    }
}

internal class PersonalNoteSession {
    var sent: JsonObject? = null
    var received: JsonObject? = null
    var capabilitiesReceived = false
    var grantsReceived = false
    var ownSettingsReceived = false

    fun ready(local: JsonObject?, remote: JsonObject?) = capabilitiesReceived && grantsReceived && ownSettingsReceived &&
        PersonalNoteMode.samePolicy(local, sent) &&
        PersonalNoteMode.samePolicy(remote, received) && PersonalNoteMode.ready(sent, received, true, true)
}
