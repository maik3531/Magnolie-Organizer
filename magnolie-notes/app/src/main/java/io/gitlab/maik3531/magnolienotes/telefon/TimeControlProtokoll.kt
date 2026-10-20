package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.ZeitSteuerBefehl
import io.gitlab.maik3531.magnolienotes.daten.ZeitSteuerErgebnis
import io.gitlab.maik3531.magnolienotes.daten.ZeitSteuerung
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import kotlinx.serialization.json.*

/** Timer commands are independent of TimeSync records and Notes content actors. */
internal object TimeControlProtokoll {
    const val CAPABILITY = "personal_tasks_sync"
    const val VERSION = 13
    const val MAX_WIRE_BYTES = 192 * 1024
    const val REQUEST = "time_tracking.control_request"
    const val REPORT = "time_tracking.control_report"
    val KINDS = setOf(REQUEST, REPORT)
    private val errors = setOf("none", "not_granted", "unsupported_feature", "conflict", "no_running_entry",
        "already_running", "save_failed", "protocol", "unknown")

    fun request(requestId: String, restoreEpoch: String = "", command: ZeitSteuerBefehl? = null): JsonObject = buildJsonObject {
        put("format", VERSION); put("request_id", requestId); put("action", command?.action ?: "read")
        put("operation_id", command?.operationId ?: ""); put("expected_revision", command?.expectedRevision ?: "")
        put("restore_epoch", restoreEpoch); put("entry_id", command?.entryId ?: "")
        put("activity", command?.activity ?: ""); put("note", command?.note ?: "")
    }.also(::validateRequest)

    fun validateRequest(body: JsonObject) {
        TelefonNachrichten.exact(body, setOf("format", "request_id", "action", "operation_id", "expected_revision", "restore_epoch", "entry_id", "activity", "note"))
        require(body.long("format") == VERSION.toLong()); TelefonNachrichten.uuid4(body.string("request_id"))
        require(body.string("restore_epoch").length <= 256)
        if (body.string("action") == "read") {
            require(listOf("operation_id", "expected_revision", "restore_epoch", "entry_id", "activity", "note").all { body.string(it).isEmpty() })
        } else command(body).validate()
    }

    fun command(body: JsonObject): ZeitSteuerBefehl = ZeitSteuerBefehl(body.string("operation_id"), body.string("action"),
        body.string("expected_revision"), body.string("entry_id"), body.string("activity"), body.string("note")).validate()

    /** A result may be supplied only after the existing native writer has committed it. */
    fun report(requestId: String, state: ZeiterfassungStand, restoreEpoch: String, nowMs: Long,
               applied: ZeitSteuerErgebnis? = null, runtimeRequest: String = "none"): JsonObject {
        state.validate(); require(applied == null || applied.state == state)
        val active = state.entries.filter { !it.deleted && it.endMinute == null }
        require(active.size <= 1)
        return buildJsonObject {
            put("format", VERSION); put("request_id", requestId); put("operation_id", applied?.receipt?.operationId ?: "")
            put("status", if (applied?.duplicate == true) "duplicate" else "ok"); put("error", "none")
            put("restore_epoch", restoreEpoch); put("revision", ZeitSteuerung.revision(state)); put("enabled", state.enabled)
            put("entries", TimeSyncProtokoll.encodeRecords(active)); put("paused", active.singleOrNull()?.let { state.isPaused(it, nowMs / 60000) } ?: false)
            put("server_minute", nowMs / 60000); put("operation_applied", applied != null); put("persisted", applied != null)
            put("applied_entry_id", applied?.receipt?.entryId ?: "")
            put("applied_clock", JsonObject(applied?.receipt?.clock.orEmpty().mapValues { JsonPrimitive(it.value) }))
            put("runtime_request", runtimeRequest)
        }.also(::validateReport)
    }

    fun rejected(requestId: String, operationId: String, error: String): JsonObject = buildJsonObject {
        put("format", VERSION); put("request_id", requestId); put("operation_id", operationId)
        put("status", "rejected"); put("error", error); put("restore_epoch", ""); put("revision", ""); put("enabled", false)
        put("entries", JsonArray(emptyList())); put("paused", false); put("server_minute", 0)
        put("operation_applied", false); put("persisted", false); put("applied_entry_id", ""); put("applied_clock", JsonObject(emptyMap()))
        put("runtime_request", "none")
    }.also(::validateReport)

    fun validateReport(body: JsonObject) {
        TelefonNachrichten.exact(body, setOf("format", "request_id", "operation_id", "status", "error", "restore_epoch", "revision", "enabled",
            "entries", "paused", "server_minute", "operation_applied", "persisted", "applied_entry_id", "applied_clock", "runtime_request"))
        require(body.long("format") == VERSION.toLong()); TelefonNachrichten.uuid4(body.string("request_id"))
        val operation = body.string("operation_id"); if (operation.isNotEmpty()) TelefonNachrichten.uuid4(operation)
        val status = body.string("status"); require(status in setOf("ok", "duplicate", "rejected"))
        require(body.string("error") in errors && body.string("restore_epoch").length <= 256)
        val enabled = boolean(body, "enabled"); val paused = boolean(body, "paused")
        val applied = boolean(body, "operation_applied"); val persisted = boolean(body, "persisted")
        require(body.string("runtime_request") in setOf("none", "requested", "failed"))
        require(body.long("server_minute") in 0..4223371679L)
        val records = body["entries"] as? JsonArray ?: error("invalid_timer_records")
        require(records.size <= 1)
        val clock = body["applied_clock"] as? JsonObject ?: error("invalid_timer_clock")
        if (status == "rejected") {
            require(body.string("error") != "none" && body.string("restore_epoch").isEmpty() && body.string("revision").isEmpty() &&
                !enabled && !paused && !applied && !persisted && records.isEmpty() && clock.isEmpty() && body.string("applied_entry_id").isEmpty() && body.long("server_minute") == 0L && body.string("runtime_request") == "none")
            return
        }
        require(body.string("error") == "none" && ZeitSteuerung.hashPattern.matches(body.string("revision")))
        val entries = TimeSyncProtokoll.decodeRecords(body)
        entries.forEach { entry -> entry.clock.keys.forEach(TelefonNachrichten::uuid4) }
        require(entries.all { !it.deleted && it.endMinute == null } && (entries.isNotEmpty() || !paused))
        if (operation.isEmpty()) require(status == "ok" && !applied && !persisted && body.string("applied_entry_id").isEmpty() && clock.isEmpty() && body.string("runtime_request") == "none")
        else {
            require(applied && persisted && clock.size in 1..32); TelefonNachrichten.uuid4(body.string("applied_entry_id"))
            for ((actor, value) in clock) {
                TelefonNachrichten.uuid4(actor)
                require(value is JsonPrimitive && !value.isString && value.content.toLongOrNull() in 1L..9007199254740991L)
            }
        }
    }

    private fun boolean(body: JsonObject, name: String): Boolean {
        val value = body[name] as? JsonPrimitive ?: error("invalid_timer_boolean")
        require(!value.isString); return value.booleanOrNull ?: error("invalid_timer_boolean")
    }
}
