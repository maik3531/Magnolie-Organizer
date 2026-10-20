package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.security.MessageDigest
import java.time.ZoneId
import java.util.UUID

/** Native command inputs; transport consent and source ownership remain the caller's responsibility. */
@Serializable
internal data class ZeitSteuerBefehl(val operationId: String, val action: String, val expectedRevision: String,
    val entryId: String = "", val activity: String = "", val note: String = "") {
    fun validate(): ZeitSteuerBefehl {
        require(ZeitSteuerung.uuid4(operationId) && action in setOf("start", "pause", "resume", "finish"))
        require(ZeitSteuerung.hashPattern.matches(expectedRevision))
        require(if (action == "start") entryId.isEmpty() else ZeitSteuerung.uuid4(entryId))
        require(activity.length <= 120 && note.length <= 20000)
        require(action == "start" || activity.isEmpty() && note.isEmpty())
        return this
    }
}

/** This receipt is stored with the timer change, never in a separately committed phone inbox. */
@Serializable
data class ZeitSteuerBeleg(val operationId: String, val peerKeyHash: String, val requestHash: String,
    val restoreEpoch: String, val action: String, val entryId: String, val clock: Map<String, Long>, val appliedMs: Long) {
    fun validate(): ZeitSteuerBeleg {
        require(ZeitSteuerung.uuid4(operationId) && ZeitSteuerung.uuid4(entryId))
        require(ZeitSteuerung.hashPattern.matches(peerKeyHash) && ZeitSteuerung.hashPattern.matches(requestHash))
        require(restoreEpoch.length <= 256 && action in setOf("start", "pause", "resume", "finish"))
        require(appliedMs in 0L..253402300799999L && clock.size in 1..32)
        require(clock.all { (id, count) -> runCatching { UUID.fromString(id).toString() == id }.getOrDefault(false) && count in 1L..9007199254740991L })
        return this
    }
}

internal data class ZeitSteuerErgebnis(val state: ZeiterfassungStand, val receipt: ZeitSteuerBeleg, val duplicate: Boolean)

/** Uses the same start/pause/resume/finish domain handlers as the Notes UI. */
internal object ZeitSteuerung {
    internal val hashPattern = Regex("^[a-f0-9]{64}$")
    private val json = Json { encodeDefaults = true }
    internal fun uuid4(value: String) = runCatching { UUID.fromString(value).toString() == value && value[14] == '4' }.getOrDefault(false)
    private fun hash(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
    fun revision(state: ZeiterfassungStand): String = hash(json.encodeToString(state.validate()))

    fun apply(state: ZeiterfassungStand, command: ZeitSteuerBefehl, peerKeyHash: String, restoreEpoch: String,
              nowMs: Long = System.currentTimeMillis(), nativeZone: String = ZoneId.systemDefault().id): ZeitSteuerErgebnis {
        state.validate(); command.validate()
        require(hashPattern.matches(peerKeyHash) && restoreEpoch.length <= 256)
        require(nowMs in 0L..253402300799999L); ZoneId.of(nativeZone)
        val requestHash = hash(json.encodeToString(command))
        state.controlReceipts.find { it.operationId == command.operationId }?.let { receipt ->
            check(receipt.peerKeyHash == peerKeyHash && receipt.restoreEpoch == restoreEpoch && receipt.requestHash == requestHash) { "timer_operation_reused" }
            return ZeitSteuerErgebnis(state, receipt, true)
        }
        check(revision(state) == command.expectedRevision) { "timer_revision_changed" }
        check(state.enabled) { "timer_disabled" }
        val active = state.entries.filter { !it.deleted && it.endMinute == null }
        check(active.size <= 1) { "timer_running_conflict" }
        val changed = if (command.action == "start") {
            check(active.isEmpty()) { "timer_already_running" }
            check(state.entries.none { it.id == command.operationId } && command.operationId !in state.removedIds) { "timer_identity_reused" }
            state.start(Zeiteintrag(id = command.operationId, startMinute = nowMs / 60000, zone = nativeZone,
                type = command.activity, note = command.note, modifiedMs = nowMs))
        } else {
            val entry = active.singleOrNull() ?: error("timer_not_running")
            check(entry.id == command.entryId) { "timer_running_identity_changed" }
            when (command.action) {
                "pause" -> state.pause(entry, nowMs)
                "resume" -> state.resume(entry, nowMs)
                else -> state.finish(entry, nowMs)
            }
        }.prepareSharedPlans(nowMs).validate()
        val id = if (command.action == "start") command.operationId else command.entryId
        val receipt = ZeitSteuerBeleg(command.operationId, peerKeyHash, requestHash, restoreEpoch, command.action,
            id, changed.entries.single { it.id == id }.clock.toMap(), nowMs).validate()
        return ZeitSteuerErgebnis(changed.copy(controlReceipts = (changed.controlReceipts + receipt).takeLast(128)).validate(), receipt, false)
    }
}
