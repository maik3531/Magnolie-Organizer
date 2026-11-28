package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.content.ContentValues
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import io.gitlab.maik3531.magnolienotes.daten.AnhangPruefung
import io.gitlab.maik3531.magnolienotes.daten.PersonalSync
import java.io.OutputStream
import java.security.MessageDigest

internal val PERSONAL_SYNC_DATA_KINDS = arrayOf(
    "personal_sync.request", "personal_sync.batch", "personal_sync.report", "personal_sync.attachment_request",
    "personal_sync.attachment_chunk", "personal_sync.attachment_result", "personal_sync.deletion_proposals",
    "personal_sync.deletion_decision")

class TelefonDatenbank(context: Context) : SQLiteOpenHelper(context, "magnolie_phone.db", null, 7) {
    override fun onConfigure(db: SQLiteDatabase) { db.enableWriteAheadLogging(); db.setForeignKeyConstraintsEnabled(true) }
    override fun onOpen(db: SQLiteDatabase) {
        super.onOpen(db)
        val columns = mutableSetOf<String>()
        db.rawQuery("PRAGMA table_info(personal_attachment_transfer)", null).use { while (it.moveToNext()) columns += it.getString(1) }
        if (columns.isNotEmpty() && "metadata" !in columns) db.execSQL("ALTER TABLE personal_attachment_transfer ADD COLUMN metadata BLOB")
    }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE outbox(message_id TEXT PRIMARY KEY,peer_id TEXT NOT NULL,kind TEXT NOT NULL,created_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,attempts INTEGER NOT NULL,next_attempt_ms INTEGER NOT NULL,last_error TEXT NOT NULL,transport_policy TEXT NOT NULL DEFAULT 'any')")
        db.execSQL("CREATE TABLE inbox(message_id TEXT NOT NULL,peer_id TEXT NOT NULL,kind TEXT NOT NULL,received_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,state TEXT NOT NULL,PRIMARY KEY(peer_id,message_id))")
        db.execSQL("CREATE TABLE dedupe(message_id TEXT NOT NULL,peer_id TEXT NOT NULL,result TEXT NOT NULL,error TEXT NOT NULL,seen_ms INTEGER NOT NULL,PRIMARY KEY(peer_id,message_id))")
        db.execSQL("CREATE TABLE event_dedupe(event_key TEXT PRIMARY KEY,seen_ms INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE meta(key TEXT PRIMARY KEY,value BLOB NOT NULL)")
        db.execSQL("CREATE TABLE personal_batch(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,sequence INTEGER NOT NULL,batch_id TEXT NOT NULL UNIQUE,message_id TEXT NOT NULL UNIQUE,received_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,last INTEGER NOT NULL,PRIMARY KEY(peer_id,run_id,reply,sequence))")
        db.execSQL("CREATE TABLE personal_run(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,trigger TEXT NOT NULL,transport_policy TEXT NOT NULL,payload BLOB NOT NULL,created_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,applied_request INTEGER NOT NULL DEFAULT 0,applied_reply INTEGER NOT NULL DEFAULT 0,responded INTEGER NOT NULL DEFAULT 0,reported INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(peer_id,run_id))")
        createAttachmentTables(db)
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.execSQL("CREATE TABLE IF NOT EXISTS event_dedupe(event_key TEXT PRIMARY KEY,seen_ms INTEGER NOT NULL)")
        }
        if (oldVersion < 3) {
            db.execSQL("DROP TABLE IF EXISTS sms_effect")
            db.delete("outbox", "kind IN (?,?,?)", arrayOf("sms_send.command", "sms_send.result", "sms_received.event"))
            db.delete("inbox", "kind IN (?,?,?)", arrayOf("sms_send.command", "sms_send.result", "sms_received.event"))
        }
        if (oldVersion < 4) {
            db.execSQL("ALTER TABLE outbox ADD COLUMN transport_policy TEXT NOT NULL DEFAULT 'any'")
            db.execSQL("CREATE TABLE IF NOT EXISTS personal_batch(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,sequence INTEGER NOT NULL,batch_id TEXT NOT NULL UNIQUE,message_id TEXT NOT NULL UNIQUE,received_ms INTEGER NOT NULL,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL,last INTEGER NOT NULL,PRIMARY KEY(peer_id,run_id,reply,sequence))")
        }
        if (oldVersion < 5) {
            db.execSQL("CREATE TABLE IF NOT EXISTS personal_run(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,trigger TEXT NOT NULL,transport_policy TEXT NOT NULL,payload BLOB NOT NULL,applied_request INTEGER NOT NULL DEFAULT 0,applied_reply INTEGER NOT NULL DEFAULT 0,responded INTEGER NOT NULL DEFAULT 0,reported INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(peer_id,run_id))")
        }
        if (oldVersion < 6) createAttachmentTables(db)
        if (oldVersion < 7) {
            db.execSQL("ALTER TABLE personal_run ADD COLUMN created_ms INTEGER NOT NULL DEFAULT 0")
            db.execSQL("ALTER TABLE personal_run ADD COLUMN expires_ms INTEGER NOT NULL DEFAULT 0")
            val now = System.currentTimeMillis()
            db.execSQL("UPDATE personal_run SET created_ms=?,expires_ms=? WHERE expires_ms=0", arrayOf(now, now + 86_400_000L))
        }
    }

    private fun createAttachmentTables(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS personal_attachment_transfer(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,records_hash TEXT NOT NULL,sha256 TEXT NOT NULL,direction TEXT NOT NULL,size INTEGER NOT NULL,mime TEXT NOT NULL,transport_policy TEXT NOT NULL,expires_ms INTEGER NOT NULL,complete INTEGER NOT NULL DEFAULT 0,metadata BLOB,PRIMARY KEY(peer_id,run_id,reply,records_hash,sha256,direction))")
        db.execSQL("CREATE TABLE IF NOT EXISTS personal_attachment_chunk(peer_id TEXT NOT NULL,run_id TEXT NOT NULL,reply INTEGER NOT NULL,records_hash TEXT NOT NULL,sha256 TEXT NOT NULL,direction TEXT NOT NULL,chunk_index INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(peer_id,run_id,reply,records_hash,sha256,direction,chunk_index))")
    }

    fun deletePeer(peerId: String) = writableDatabase.inTransaction {
        listOf("outbox", "inbox", "dedupe", "personal_batch", "personal_run", "personal_attachment_chunk",
            "personal_attachment_transfer").forEach { delete(it, "peer_id=?", arrayOf(peerId)) }
        // Retain function choices for a freshly confirmed pairing with the same
        // UUID/public key. SharedSyncStorage authenticates that binding; this
        // record carries neither Android permissions nor session authority.
        delete("meta", "key LIKE ? AND key NOT GLOB ?", arrayOf("%:$peerId:%",
            "personal_shared_settings:$peerId:*:consent"))
        delete("event_dedupe", null, null)
    }
}

internal inline fun <T> SQLiteDatabase.inTransaction(block: SQLiteDatabase.() -> T): T {
    beginTransaction()
    return try { block().also { setTransactionSuccessful() } } finally { endTransaction() }
}

// Reject new work rather than evicting live replay proofs or pending mutations.
internal fun SQLiteDatabase.phoneCapacity(table: String, bytes: Int = 0, rows: Int = 8192) {
    val payload = when (table) {
        "outbox", "inbox", "personal_batch", "personal_run" -> "COALESCE(SUM(length(payload)),0)"
        "personal_attachment_transfer" -> "COALESCE(SUM(length(metadata)),0)"
        "meta" -> "COALESCE(SUM(length(value)),0)"
        "event_dedupe" -> "COALESCE(SUM(length(CAST(event_key AS BLOB))),0)"
        else -> "0"
    }
    rawQuery("SELECT COUNT(*),$payload FROM $table", null).use {
        it.moveToFirst()
        if (it.getLong(0) >= rows || it.getLong(1) + bytes > 50L * 1024 * 1024)
            throw TelefonProtokollFehler("Telefon-Warteschlange ist voll.")
    }
}

data class TelefonOutboxEintrag(val messageId: String, val payload: JsonObject)

internal data class DeletionDecisionAck(val decisionId: String, val state: String)

internal data class PersonalRunIndex(
    val peerId: String, val runId: String, val trigger: String, val transportPolicy: String,
    val createdMs: Long, val expiresMs: Long, val appliedRequest: Boolean = false,
    val appliedReply: Boolean = false, val responded: Boolean = false, val reported: Boolean = false,
    val actor: Boolean = false, val actorStopped: Boolean = false
)

internal object PersonalRunAuthentication {
    fun effectiveExpiry(wireExpiresMs: Long, now: Long, existingExpiresMs: Long? = null): Long {
        val effective = minOf(wireExpiresMs, now + 86_400_000L, existingExpiresMs ?: Long.MAX_VALUE)
        if (effective <= now) throw TelefonProtokollFehler("Personal-Sync-Lauf ist abgelaufen.")
        return effective
    }

    fun envelope(index: PersonalRunIndex, request: JsonObject) = buildJsonObject {
        put("peer_id", JsonPrimitive(index.peerId)); put("run_id", JsonPrimitive(index.runId))
        put("trigger", JsonPrimitive(index.trigger)); put("transport_policy", JsonPrimitive(index.transportPolicy))
        put("created_ms", JsonPrimitive(index.createdMs)); put("expires_ms", JsonPrimitive(index.expiresMs))
        put("applied_request", JsonPrimitive(index.appliedRequest)); put("applied_reply", JsonPrimitive(index.appliedReply))
        put("responded", JsonPrimitive(index.responded)); put("reported", JsonPrimitive(index.reported))
        put("modules", request.getValue("modules")); put("request", request)
        if (index.actor) put("actor", JsonPrimitive(true))
        if (index.actorStopped) { require(index.actor); put("actor_stopped", JsonPrimitive(true)) }
    }

    fun authenticate(envelope: JsonObject, index: PersonalRunIndex): JsonObject {
        val request = envelope["request"] as? JsonObject
            ?: throw TelefonProtokollFehler("Nicht authentifizierte Personal-Sync-Metadaten.")
        val modules = request["modules"] as? JsonArray
        val expectedPolicy = PersonalAutoSync.policy(index.trigger)
        if (request["run_id"] != JsonPrimitive(index.runId) || request["trigger"] != JsonPrimitive(index.trigger) ||
            modules == null || modules.any { it !is JsonPrimitive } || modules.map { (it as JsonPrimitive).content } !in
                listOf(listOf("notes"), listOf("tasks"), listOf("notes", "tasks")) ||
            index.transportPolicy != expectedPolicy ||
            index.actor && index.trigger != "manual" ||
            index.actorStopped && !index.actor ||
            index.createdMs < 0 || index.expiresMs <= index.createdMs || envelope != this.envelope(index, request))
            throw TelefonProtokollFehler("Manipulierte Personal-Sync-Metadaten.")
        return request
    }

    fun requireCurrent(index: PersonalRunIndex, now: Long): PersonalRunIndex {
        if (index.expiresMs <= now) throw TelefonProtokollFehler("Personal-Sync-Lauf ist abgelaufen.")
        return index
    }
}

class TelefonQueue internal constructor(context: Context, private val storage: TelefonPayloadStorage,
                                       private val restoreEpoch: () -> String = { "" }) {
    private val helper = TelefonDatenbank(context.applicationContext)

    internal fun hasSharedSettings(peerId: String): Boolean = helper.readableDatabase.query("meta", arrayOf("key"),
        "key LIKE ?", arrayOf("personal_shared_settings:$peerId:%:consent"), null, null, null, "1").use { it.moveToFirst() }

    internal fun sharedSettingsStorage(binding: () -> SharedSettingsBinding?, restoreBlocked: () -> Boolean) =
        SharedSyncStorage({ helper.writableDatabase }, storage, binding, restoreBlocked)

    internal fun mediaSettingsStorage(binding: () -> MediaSettingsBinding?, restoreBlocked: () -> Boolean,
        legacyProjection: (MediaSettingsBinding) -> JsonObject = { MediaSyncSettings.create(it.localActor) }) =
        MediaSyncStorage({ helper.writableDatabase }, storage, binding, restoreBlocked, legacyProjection)

    internal fun hasMediaSettings(peerId: String): Boolean {
        val db = helper.readableDatabase
        db.rawQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_shared_settings'", null).use {
            if (!it.moveToFirst()) return false
        }
        return db.query("native_media_shared_settings", arrayOf("peer_id"), "peer_id=?", arrayOf(peerId), null, null, null, "1").use { it.moveToFirst() }
    }

    internal fun actorJournal(sourceLock: Any, bookLock: Any, currentSource: (String, String) -> String?) =
        PersonalSyncActorJournal(helper, storage, currentSource, restoreEpoch, sourceLock = sourceLock, bookLock = bookLock)

    internal fun containsScopedRun(peerId: String, runId: String): Boolean = helper.readableDatabase.query(
        "meta", arrayOf("key"), "key=?", arrayOf("personal_scope:$peerId:$runId"), null, null, null, "1").use { it.moveToFirst() }

    internal fun hasActiveScopedRun(peerId: String, now: Long = System.currentTimeMillis()): Boolean =
        hasActiveScopedRunIn(helper.readableDatabase, peerId, now)

    private fun hasActiveScopedRunIn(db: SQLiteDatabase, peerId: String, now: Long, connectionAuthority: String? = null): Boolean =
        db.query("personal_run", arrayOf("run_id"), "peer_id=?", arrayOf(peerId), null, null, null).use { cursor ->
            while (cursor.moveToNext()) {
                val runId = cursor.getString(0)
                val marker = readScopeRun(db, peerId, runId) ?: continue
                val owner = marker["connection_authority"]
                if (owner != null && owner != JsonPrimitive(connectionAuthority)) continue
                val run = authenticatedRun(peerId, runId, db)?.first ?: continue
                if (!run.reported && run.expiresMs > now) return@use true
            }
            false
        }

    internal fun outboxPersonalMessage(peerId: String, messageId: String): JsonObject? = readOutboxMessage(peerId, messageId, true)

    internal fun outboxWireMessage(peerId: String, messageId: String): JsonObject? = readOutboxMessage(peerId, messageId, false)

    private fun readOutboxMessage(peerId: String, messageId: String, personalOnly: Boolean): JsonObject? = helper.readableDatabase.query(
        "outbox", arrayOf("kind", "payload"), "peer_id=? AND message_id=?", arrayOf(peerId, messageId), null, null, null).use {
        if (!it.moveToFirst() || personalOnly && it.getString(0) !in PERSONAL_SYNC_DATA_KINDS) return@use null
        val clear = storage.decryptPayload(it.getBlob(1), "outbox", messageId)
        try { TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject } finally { clear.fill(0) }
    }

    fun queue(peerId: String, kind: String, body: JsonObject, ttlMs: Long, now: Long = System.currentTimeMillis(),
              transportPolicy: String = "any", actorRunId: String? = null): JsonObject {
        require(transportPolicy in setOf("any", "wifi_only"))
        if (kind == SharedSyncSettings.KIND) { SharedSyncSettings.validate(body); require(ttlMs <= 86_400_000) }
        if (kind == MediaSyncSettings.KIND) { MediaSyncSettings.validate(body); require(ttlMs <= 86_400_000) }
        if (kind == PhoneContentScope.KIND) { PhoneContentScope.validatePart(body); require(ttlMs <= 60_000) }
        val message = TelefonNachrichten.message(kind, body, ttlMs, now)
        return writableInsert(peerId, message, transportPolicy = transportPolicy, actorRunId = actorRunId)
    }

    fun queuePrepared(peerId: String, message: JsonObject, transportPolicy: String = "any", actorRunId: String? = null) {
        require(transportPolicy in setOf("any", "wifi_only"))
        writableInsert(peerId, message, transportPolicy = transportPolicy, actorRunId = actorRunId)
    }

    private fun writableInsert(peerId: String, message: JsonObject, db: SQLiteDatabase = helper.writableDatabase,
                                transportPolicy: String = "any", actorRunId: String? = null): JsonObject = db.inTransaction {
        require(!PhoneWebcamControl.reserved(message)) { "webcam_controls_cannot_be_persisted" }
        require(!PhoneScreenControl.reserved(message)) { "screen_controls_cannot_be_persisted" }
        val statusBody = message["body"] as? JsonObject
        require(!message.string("kind").startsWith("device_status.") ||
            statusBody?.containsKey("identifiers") != true && statusBody?.get("version") != JsonPrimitive(4))
        require(!PersonalSyncActor.isReservedKind(message.string("kind")))
        val runId = if (message.string("kind") in PERSONAL_SYNC_DATA_KINDS)
            (statusBody?.get("run_id") as? JsonPrimitive)?.takeIf { it.isString }?.content else null
        val classified = runId != null && sealedActorRun(peerId, runId, db)
        if (actorRunId != null) require(classified && actorRunId == runId) { "Actor context does not match protected run classification" }
        val wire = if (classified) {
            val actorId = requireNotNull(runId)
            val run = requireNotNull(authenticatedRun(peerId, actorId, db)) { "Actor run is unavailable" }.first
            require(run.actor && !run.actorStopped && run.expiresMs > System.currentTimeMillis()) { "Actor run is inactive" }
            PersonalSyncActor.wireMessage(message, actorId)
        } else message
        val id = message.string("message_id")
        val payload = storage.encryptPayload(TelefonKanonisch.bytes(wire), "outbox", id)
        db.phoneCapacity("outbox", payload.size)
        val values = ContentValues().apply {
            put("message_id", id); put("peer_id", peerId); put("kind", message.string("kind"))
            put("created_ms", message.long("created_ms")); put("expires_ms", message.long("expires_ms"))
            put("payload", payload)
            put("attempts", 0); put("next_attempt_ms", message.long("created_ms")); put("last_error", "")
            put("transport_policy", transportPolicy)
        }
        db.insertOrThrow("outbox", null, values)
        wire
    }

    internal fun due(peerId: String, transport: TelefonTransportArt, now: Long = System.currentTimeMillis(),
                     connectionOnly: Boolean = false): List<TelefonOutboxEintrag> {
        val result = mutableListOf<TelefonOutboxEintrag>()
        val policies = when {
            connectionOnly -> "transport_policy GLOB 'connection_only:*' AND last_error=''"
            transport == TelefonTransportArt.BLUETOOTH -> "transport_policy='any'"
            else -> "transport_policy NOT GLOB 'connection_only:*'"
        }
        helper.writableDatabase.inTransaction {
            val stale = mutableListOf<String>()
            query("outbox", arrayOf("message_id", "peer_id", "kind", "created_ms", "expires_ms",
                "transport_policy", "payload"), "peer_id=? AND next_attempt_ms<=? AND $policies",
                arrayOf(peerId, now.toString()), null, null,
                "CASE kind WHEN 'capabilities.update' THEN 0 WHEN 'grants.update' THEN 1 WHEN 'personal_sync.settings' THEN 2 WHEN 'personal_sync.note_settings' THEN 3 WHEN 'personal_sync.time_settings' THEN 4 WHEN 'personal_sync.custom_settings' THEN 5 WHEN 'personal_sync.shared_settings' THEN 6 WHEN 'personal_sync.content_scope' THEN 7 WHEN 'personal_sync.request' THEN 8 ELSE 9 END,created_ms,message_id", "32").use { cursor ->
                while (cursor.moveToNext()) {
                    val id = cursor.getString(0)
                    var clear: ByteArray? = null
                    try {
                        clear = storage.decryptPayload(cursor.getBlob(6), "outbox", id)
                        val message = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                        val kind = cursor.getString(2)
                        val semantic = PersonalSyncActor.semanticMessage(message)
                        if (cursor.getString(1) != peerId || message.string("message_id") != id ||
                            semantic.string("kind") != kind || message.long("created_ms") != cursor.getLong(3) ||
                            message.long("expires_ms") != cursor.getLong(4) || cursor.getLong(4) <= now) {
                            stale += id; continue
                        }
                        val stored = cursor.getString(5)
                        if (connectionOnly) {
                            val initial = connectionInitialMarker(this, peerId, message, now)
                            if (initial != null && stored == connectionPolicy(initial, message.getValue("body").jsonObject.string("run_id"))) {
                                if (kind == "personal_sync.request" || initial["request_accepted"] == JsonPrimitive(true))
                                    result += TelefonOutboxEintrag(id, message)
                            } else if (connectionCompletionPolicy(this, peerId, message, now) == stored)
                                result += TelefonOutboxEintrag(id, message)
                            else stale += id
                            continue
                        }
                        val effective = if (kind in PERSONAL_SYNC_DATA_KINDS) {
                            val body = semantic["body"] as JsonObject
                            val run = authenticatedRun(peerId, body.string("run_id"), this)?.first
                            if (run == null || run.expiresMs <= now) { stale += id; continue }
                            if (run.actor && run.actorStopped) continue
                            run.transportPolicy
                        } else stored
                        if (effective != stored || effective !in setOf("any", "wifi_only")) {
                            stale += id; continue
                        }
                        if (effective == "wifi_only" && transport != TelefonTransportArt.WIFI) continue
                        result += TelefonOutboxEintrag(id, message)
                    } catch (_: Exception) {
                        stale += id
                    } finally {
                        clear?.fill(0)
                    }
                }
            }
            stale.distinct().forEach { delete("outbox", "peer_id=? AND message_id=?", arrayOf(peerId, it)) }
        }
        return result
    }

    fun sent(messageId: String, attempts: Int, now: Long = System.currentTimeMillis()) {
        val values = ContentValues().apply {
            put("attempts", attempts + 1)
            put("next_attempt_ms", TelefonWiederholung.naechsterVersuch(now, attempts))
        }
        helper.writableDatabase.update("outbox", values, "message_id=?", arrayOf(messageId))
    }

    internal fun acknowledge(peerId: String, messageId: String, status: String = "accepted",
                             error: String = "none"): DeletionDecisionAck? = helper.writableDatabase.inTransaction {
        val decisionId = query("outbox", arrayOf("payload"),
            "peer_id=? AND message_id=? AND kind='personal_sync.deletion_decision'", arrayOf(peerId, messageId),
            null, null, null).use { cursor -> if (!cursor.moveToFirst()) null else {
                val clear = storage.decryptPayload(cursor.getBlob(0), "outbox", messageId)
                try {
                    val message = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                    val body = PersonalSyncActor.semanticMessage(message)["body"] as JsonObject
                    (body["decision_id"] as JsonPrimitive).content
                } finally { clear.fill(0) }
            } }
        if (decisionId == null) {
            if (status == "rejected" && error == "temporary_failure") return@inTransaction null
            delete("outbox", "peer_id=? AND message_id=?", arrayOf(peerId, messageId))
            return@inTransaction null
        }
        val state = when {
            status in setOf("accepted", "duplicate") -> "accepted"
            error in setOf("conflict", "restore_unavailable", "invalid_schema", "permanent_failure") -> "terminal:$error"
            error == "expired" -> "expired"
            else -> "temporary:$error"
        }
        if (!state.startsWith("temporary:"))
            delete("outbox", "peer_id=? AND message_id=?", arrayOf(peerId, messageId))
        DeletionDecisionAck(decisionId, state)
    }

    fun outboxPolicy(peerId: String, messageId: String): String? = helper.readableDatabase.query(
        "outbox", arrayOf("transport_policy", "kind", "payload", "peer_id", "created_ms", "expires_ms"),
        "peer_id=? AND message_id=?", arrayOf(peerId, messageId),
        null, null, null).use { cursor ->
        if (!cursor.moveToFirst()) return@use null
        if (cursor.getString(0) !in setOf("any", "wifi_only")) return@use "invalid"
        val stored = cursor.getString(0); val kind = cursor.getString(1)
        if (kind !in PERSONAL_SYNC_DATA_KINDS) return@use stored
        val clear = storage.decryptPayload(cursor.getBlob(2), "outbox", messageId)
        try {
            val message = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
            val semantic = PersonalSyncActor.semanticMessage(message)
            if (cursor.getString(3) != peerId || message.string("message_id") != messageId ||
                semantic.string("kind") != kind || message.long("created_ms") != cursor.getLong(4) ||
                message.long("expires_ms") != cursor.getLong(5)) return@use "invalid"
            val body = semantic["body"] as JsonObject
            if (authenticatedRun(peerId, body.string("run_id"))?.first?.actorStopped == true) return@use "invalid"
            val durable = personalRunPolicy(peerId, body.string("run_id"))
            if (durable == stored) durable else "invalid"
        } finally { clear.fill(0) }
    }

    fun attempts(messageId: String): Int = helper.readableDatabase.query("outbox", arrayOf("attempts"),
        "message_id=?", arrayOf(messageId), null, null, null).use { if (it.moveToFirst()) it.getInt(0) else 0 }

    fun duplicateResult(peerId: String, messageId: String): Pair<String, String>? =
        helper.readableDatabase.query("dedupe", arrayOf("result", "error"), "peer_id=? AND message_id=?",
            arrayOf(peerId, messageId), null, null, null).use { cursor ->
            if (cursor.moveToFirst()) TelefonNachrichten.duplicateAck(cursor.getString(0), cursor.getString(1)) else null
        }

    fun receivedMatches(peerId: String, message: JsonObject): Boolean = helper.readableDatabase.query(
        "inbox", arrayOf("payload"), "peer_id=? AND message_id=?", arrayOf(peerId, message.string("message_id")),
        null, null, null).use { cursor ->
        if (!cursor.moveToFirst()) false else {
            val clear = storage.decryptPayload(cursor.getBlob(0), "inbox", message.string("message_id"))
            try { TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) == message }
            finally { clear.fill(0) }
        }
    }

    fun controlApplied(peerId: String, messageId: String) {
        helper.writableDatabase.update("inbox", ContentValues().apply { put("state", "applied") },
            "peer_id=? AND message_id=? AND kind IN ('capabilities.update','grants.update')",
            arrayOf(peerId, messageId))
    }

    fun receive(peerId: String, message: JsonObject, response: JsonObject? = null,
                now: Long = System.currentTimeMillis(), validateExtra: () -> Unit = {}): Pair<String, String> = helper.writableDatabase.inTransaction {
        require(!PhoneWebcamControl.reserved(message)) { "webcam_controls_cannot_be_persisted" }
        require(!PhoneScreenControl.reserved(message)) { "screen_controls_cannot_be_persisted" }
        val id = message.string("message_id")
        query("dedupe", arrayOf("result", "error"), "peer_id=? AND message_id=?", arrayOf(peerId, id),
            null, null, null).use {
            if (it.moveToFirst()) return@inTransaction TelefonNachrichten.duplicateAck(it.getString(0), it.getString(1))
        }
        val result = runCatching { TelefonNachrichten.validate(message, now); validateExtra() }
            .fold({ "accepted" to "none" }, { "rejected" to "invalid_schema" })
        phoneCapacity("dedupe", rows = 100_000)
        if (result.first == "accepted" && response != null) writableInsert(peerId, response, this)
        writableInbox(peerId, message, result.first, now, this)
        val values = ContentValues().apply {
            put("message_id", id); put("peer_id", peerId); put("result", result.first); put("error", result.second); put("seen_ms", now)
        }
        insertOrThrow("dedupe", null, values)
        result
    }

    fun terminal(peerId: String, message: JsonObject, error: String, now: Long = System.currentTimeMillis()): Pair<String, String> =
        helper.writableDatabase.inTransaction {
            require(!PhoneScreenControl.reserved(message)) { "screen_controls_cannot_be_persisted" }
            TelefonNachrichten.validateHeader(message, now)
            val id = message.string("message_id")
            query("dedupe", arrayOf("result", "error"), "peer_id=? AND message_id=?", arrayOf(peerId, id),
                null, null, null).use {
                if (it.moveToFirst()) return@inTransaction TelefonNachrichten.duplicateAck(it.getString(0), it.getString(1))
            }
            val values = ContentValues().apply {
                put("message_id", id); put("peer_id", peerId); put("result", "rejected"); put("error", error); put("seen_ms", now)
            }
            phoneCapacity("dedupe", rows = 100_000)
            writableInbox(peerId, message, "rejected", now, this)
            insertOrThrow("dedupe", null, values)
            "rejected" to error
        }

    private fun writableInbox(peerId: String, message: JsonObject, state: String, now: Long,
                              db: SQLiteDatabase) {
        require(!PhoneWebcamControl.reserved(message)) { "webcam_controls_cannot_be_persisted" }
        val id = message.string("message_id")
        val stored = if (message.string("kind").startsWith("device_status.") && message["body"] is JsonObject)
            JsonObject(message + ("body" to JsonObject((message["body"] as JsonObject).filterKeys {
                message.string("kind") == "device_status.request" && it in setOf("request_id", "version", "include_identifiers") }))) else message
        val encrypted = storage.encryptPayload(TelefonKanonisch.bytes(stored), "inbox", id)
        db.phoneCapacity("inbox", encrypted.size)
        val values = ContentValues().apply {
            put("message_id", id); put("peer_id", peerId); put("kind", message.string("kind"))
            put("received_ms", now); put("expires_ms", message.long("expires_ms"))
            put("payload", encrypted); put("state", state)
        }
        db.insertOrThrow("inbox", null, values)
    }

    /** Private review intents reuse the encrypted inbox; they are not applied or acknowledged. */
    internal fun stageActorDeletionIntent(runId: String, message: JsonObject, outgoing: Boolean = false) =
        helper.writableDatabase.inTransaction {
            val peerId = PersonalSyncActor.storagePeer(runId)
            require(message.string("kind") in setOf("personal_sync.deletion_proposals", "personal_sync.deletion_decision"))
            require(!outgoing || message.string("kind") == "personal_sync.deletion_proposals")
            require((message.getValue("body") as JsonObject).string("run_id") == runId)
            TelefonNachrichten.validate(message)
            val envelope = buildJsonObject {
                put("peer_id", JsonPrimitive(peerId)); put("run_id", JsonPrimitive(runId))
                put("outgoing", JsonPrimitive(outgoing)); put("message", message)
            }
            val id = message.string("message_id")
            query("inbox", arrayOf("payload"), "peer_id=? AND message_id=?", arrayOf(peerId, id), null, null, null).use { row ->
                if (row.moveToFirst()) {
                    val raw = storage.decryptPayload(row.getBlob(0), "inbox", id)
                    try { require(TelefonKanonisch.json.parseToJsonElement(raw.decodeToString()) == envelope) }
                    finally { raw.fill(0) }
                    return@inTransaction
                }
            }
            val raw = TelefonKanonisch.bytes(envelope)
            val payload = try { storage.encryptPayload(raw, "inbox", id) } finally { raw.fill(0) }
            phoneCapacity("inbox", payload.size)
            insertOrThrow("inbox", null, ContentValues().apply {
                put("peer_id", peerId); put("message_id", id); put("kind", message.string("kind"))
                put("received_ms", System.currentTimeMillis()); put("expires_ms", message.long("expires_ms"))
                put("state", "actor_staged"); put("payload", payload)
            })
            Unit
        }

    internal fun actorDeletionIntents(runId: String, outgoing: Boolean = false): List<JsonObject> {
        val peerId = PersonalSyncActor.storagePeer(runId)
        return helper.readableDatabase.query("inbox", arrayOf("message_id", "payload"),
            "peer_id=? AND state='actor_staged' AND expires_ms>?", arrayOf(peerId, System.currentTimeMillis().toString()),
            null, null, "received_ms,message_id").use { rows ->
            val result = mutableListOf<JsonObject>()
            while (rows.moveToNext()) {
                val id = rows.getString(0)
                val raw = storage.decryptPayload(rows.getBlob(1), "inbox", id)
                try {
                    val envelope = TelefonKanonisch.json.parseToJsonElement(raw.decodeToString()) as JsonObject
                    require(envelope["peer_id"] == JsonPrimitive(peerId) && envelope["run_id"] == JsonPrimitive(runId))
                    val message = envelope.getValue("message") as JsonObject
                    require(message.string("message_id") == id && (message.getValue("body") as JsonObject).string("run_id") == runId)
                    TelefonNachrichten.validate(message)
                    if (message.long("expires_ms") > System.currentTimeMillis() && envelope["outgoing"] == JsonPrimitive(outgoing)) result += message
                } finally { raw.fill(0) }
            }
            result
        }
    }

    /** Native caller has already committed the exact document review. This
     * consumes only its immutable private control envelopes, never book data. */
    internal fun commitActorDeletionIntents(runId: String, expected: List<JsonObject>): Boolean =
        helper.writableDatabase.inTransaction {
            val peerId = PersonalSyncActor.storagePeer(runId)
            require(expected.size <= 256 && expected.map { it.string("message_id") }.distinct().size == expected.size)
            val stagedIds = mutableSetOf<String>()
            query("inbox", arrayOf("message_id", "payload"), "peer_id=? AND state='actor_staged'", arrayOf(peerId), null, null, null).use { rows ->
                while (rows.moveToNext()) {
                    val id = rows.getString(0); val raw = storage.decryptPayload(rows.getBlob(1), "inbox", id)
                    try {
                        val envelope = TelefonKanonisch.json.parseToJsonElement(raw.decodeToString()).jsonObject
                        if (envelope["outgoing"] == JsonPrimitive(false)) stagedIds.add(id)
                    } finally { raw.fill(0) }
                }
            }
            val expectedIds = expected.map { it.string("message_id") }.toSet()
            if (!expectedIds.containsAll(stagedIds)) return@inTransaction false
            for (message in expected) {
                require(message.string("kind") in setOf("personal_sync.deletion_proposals", "personal_sync.deletion_decision") &&
                    message.getValue("body").jsonObject.string("run_id") == runId)
                TelefonNachrichten.validate(message, message.long("created_ms"))
                val id = message.string("message_id")
                val row = query("inbox", arrayOf("state", "payload"), "peer_id=? AND message_id=?", arrayOf(peerId, id), null, null, null).use {
                    if (!it.moveToFirst()) return@inTransaction false
                    it.getString(0) to it.getBlob(1)
                }
                if (row.first !in setOf("actor_staged", "actor_processed")) return@inTransaction false
                val raw = storage.decryptPayload(row.second, "inbox", id)
                try {
                    val envelope = TelefonKanonisch.json.parseToJsonElement(raw.decodeToString()).jsonObject
                    if (envelope["peer_id"] != JsonPrimitive(peerId) || envelope["run_id"] != JsonPrimitive(runId) ||
                        envelope["outgoing"] != JsonPrimitive(false) || envelope["message"] != message) return@inTransaction false
                } finally { raw.fill(0) }
            }
            // Validate the full set before changing any one receipt.
            for (id in expectedIds) update("inbox", ContentValues().apply { put("state", "actor_processed") },
                "peer_id=? AND message_id=? AND state='actor_staged'", arrayOf(peerId, id))
            true
        }

    fun deletePeer(peerId: String) = helper.deletePeer(peerId)

    fun hasKind(peerId: String, kind: String): Boolean = helper.readableDatabase.query("outbox", arrayOf("message_id"),
        "peer_id=? AND kind=?", arrayOf(peerId, kind), null, null, null, "1").use { it.moveToFirst() }

    fun removeKind(peerId: String, kind: String) {
        helper.writableDatabase.delete("outbox", "peer_id=? AND kind=?", arrayOf(peerId, kind))
    }

    fun removeCallEvents() {
        helper.writableDatabase.delete("outbox", "kind=?", arrayOf("incoming_call_state.event"))
    }

    fun purgeNotifications(allowedPackages: Set<String>) = helper.writableDatabase.inTransaction {
        if (allowedPackages.isEmpty()) {
            delete("outbox", "kind=?", arrayOf("selected_notifications_readonly.event"))
            return@inTransaction
        }
        val removed = mutableListOf<String>()
        query("outbox", arrayOf("message_id", "payload"), "kind=?",
            arrayOf("selected_notifications_readonly.event"), null, null, null).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0)
                val clear = storage.decryptPayload(cursor.getBlob(1), "outbox", id)
                try {
                    val message = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                    if ((message["body"] as JsonObject).string("package") !in allowedPackages) removed += id
                } finally { clear.fill(0) }
            }
        }
        removed.forEach { delete("outbox", "message_id=?", arrayOf(it)) }
    }

    fun purgePersonal(peerId: String) {
        helper.writableDatabase.inTransaction {
            val slots = PERSONAL_SYNC_DATA_KINDS.joinToString(",") { "?" }
            execSQL("DELETE FROM dedupe WHERE peer_id=? AND message_id IN (SELECT message_id FROM inbox WHERE peer_id=? AND kind IN ($slots))",
                arrayOf(peerId, peerId, *PERSONAL_SYNC_DATA_KINDS))
            val arguments = arrayOf(peerId, *PERSONAL_SYNC_DATA_KINDS)
            delete("outbox", "peer_id=? AND kind IN ($slots)", arguments)
            delete("inbox", "peer_id=? AND kind IN ($slots)", arguments)
            delete("personal_batch", "peer_id=?", arrayOf(peerId))
            delete("personal_run", "peer_id=?", arrayOf(peerId))
            delete("personal_attachment_chunk", "peer_id=?", arrayOf(peerId))
            delete("personal_attachment_transfer", "peer_id=?", arrayOf(peerId))
            delete("meta", "key LIKE ?", arrayOf("personal_run:$peerId:%"))
            delete("meta", "key LIKE ?", arrayOf("personal_scope:$peerId:%"))
            delete("meta", "key LIKE ?", arrayOf("personal_report:$peerId:%"))
        }
    }

    fun purgePersonalModules(peerId: String, revoked: Set<String>) {
        if (revoked.isEmpty()) return
        val runIds = mutableListOf<String>()
        helper.readableDatabase.query("personal_run", arrayOf("run_id"), "peer_id=?",
            arrayOf(peerId), null, null, null).use { cursor -> while (cursor.moveToNext()) {
            val runId = cursor.getString(0)
            val body = authenticatedRun(peerId, runId)?.second
            if (body == null) { runIds += runId; continue }
            val modules = (body["modules"] as? JsonArray).orEmpty().map { (it as JsonPrimitive).content }.toSet()
            if (modules.any(revoked::contains)) runIds += runId
        } }
        helper.writableDatabase.inTransaction {
            runIds.forEach { runId ->
                for (table in listOf("personal_batch", "personal_attachment_chunk", "personal_attachment_transfer"))
                    delete(table, "peer_id=? AND run_id=?", arrayOf(peerId, runId))
                delete("personal_run", "peer_id=? AND run_id=?", arrayOf(peerId, runId))
                delete("meta", "key LIKE ?", arrayOf("personal_report:$peerId:$runId%"))
                delete("meta", "key=?", arrayOf("personal_scope:$peerId:$runId"))
            }
        }
        // Encrypted wire rows cannot be classified in SQL; remove only rows whose decrypted run is revoked.
        if (runIds.isNotEmpty()) helper.writableDatabase.inTransaction { purgeWireRuns(this, peerId, runIds.toSet()) }
    }

    private fun purgeWireRuns(db: SQLiteDatabase, peerId: String, runIds: Set<String>) {
        if (runIds.isEmpty()) return
        with(db) {
            for (table in listOf("outbox", "inbox")) {
                val rows = mutableListOf<String>()
                val slots = PERSONAL_SYNC_DATA_KINDS.joinToString(",") { "?" }
                query(table, arrayOf("message_id", "payload"), "peer_id=? AND kind IN ($slots)",
                    arrayOf(peerId, *PERSONAL_SYNC_DATA_KINDS), null, null, null).use { cursor -> while (cursor.moveToNext()) {
                    val id = cursor.getString(0); val clear = storage.decryptPayload(cursor.getBlob(1), table, id)
                    try {
                        val message = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                        val run = ((message["body"] as? JsonObject)?.get("run_id") as? JsonPrimitive)?.content
                        if (run in runIds) rows += id
                    } finally { clear.fill(0) }
                } }
                rows.forEach { id -> delete(table, "peer_id=? AND message_id=?", arrayOf(peerId, id)) }
                if (table == "inbox") rows.forEach { id -> delete("dedupe", "peer_id=? AND message_id=?", arrayOf(peerId, id)) }
            }
        }
    }

    fun queueDeletionDecision(peerId: String, body: JsonObject, transportPolicy: String): JsonObject {
        val decisionId = body.string("decision_id")
        helper.readableDatabase.query("outbox", arrayOf("message_id", "payload"),
            "peer_id=? AND kind='personal_sync.deletion_decision'", arrayOf(peerId), null, null, null).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0); val clear = storage.decryptPayload(cursor.getBlob(1), "outbox", id)
                try {
                    val existing = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                    if ((PersonalSyncActor.semanticMessage(existing)["body"] as JsonObject).string("decision_id") == decisionId) return existing
                } finally { clear.fill(0) }
            }
        }
        return queue(peerId, "personal_sync.deletion_decision", body, 86_400_000L,
            transportPolicy = transportPolicy)
    }

    fun purgePersonalDeletionWire(peerId: String) {
        helper.writableDatabase.inTransaction {
            val kinds = arrayOf("personal_sync.deletion_proposals", "personal_sync.deletion_decision")
            execSQL("DELETE FROM dedupe WHERE peer_id=? AND message_id IN (SELECT message_id FROM inbox WHERE peer_id=? AND kind IN (?,?))",
                arrayOf(peerId, peerId, *kinds))
            delete("outbox", "peer_id=? AND kind IN (?,?)", arrayOf(peerId, *kinds))
            delete("inbox", "peer_id=? AND kind IN (?,?)", arrayOf(peerId, *kinds))
        }
    }

    private fun attachmentPrimary(peerId: String, runId: String, reply: Boolean, recordsHash: String, hash: String,
                                  index: Int, direction: String) = "$peerId:$runId:${if (reply) 1 else 0}:$direction:$recordsHash:$hash:$index"

    private fun attachmentMetadata(peerId: String, runId: String, reply: Boolean, recordsHash: String, hash: String,
        direction: String, size: Int, mime: String, policy: String, expiresMs: Long, complete: Boolean) = buildJsonObject {
        put("peer_id", JsonPrimitive(peerId)); put("run_id", JsonPrimitive(runId)); put("reply", JsonPrimitive(reply))
        put("attachment_id", JsonPrimitive(hash)); put("records_hash", JsonPrimitive(recordsHash)); put("sha256", JsonPrimitive(hash))
        put("direction", JsonPrimitive(direction)); put("total_chunks", JsonPrimitive((size + PersonalSyncProtokoll.CHUNK_RAW - 1) / PersonalSyncProtokoll.CHUNK_RAW))
        put("size", JsonPrimitive(size)); put("mime", JsonPrimitive(mime)); put("expires_ms", JsonPrimitive(expiresMs))
        put("complete", JsonPrimitive(complete)); put("transport_policy", JsonPrimitive(policy))
    }

    private fun metadataPrimary(peerId: String, runId: String, reply: Boolean, recordsHash: String, hash: String,
        direction: String) = "$peerId:$runId:${if (reply) 1 else 0}:$direction:$recordsHash:$hash"

    private fun putAuthenticatedMetadata(values: ContentValues, peerId: String, runId: String, reply: Boolean,
        recordsHash: String, hash: String, direction: String, size: Int, mime: String, policy: String,
        expiresMs: Long, complete: Boolean = false) {
        val metadata = attachmentMetadata(peerId, runId, reply, recordsHash, hash, direction, size, mime, policy, expiresMs, complete)
        values.put("metadata", storage.encryptPayload(TelefonKanonisch.bytes(metadata), "personal_attachment_transfer",
            metadataPrimary(peerId, runId, reply, recordsHash, hash, direction)))
    }

    private fun authenticatedTransfer(peerId: String, runId: String, reply: Boolean, recordsHash: String,
        hash: String, direction: String, db: SQLiteDatabase = helper.readableDatabase): JsonObject? = db.query("personal_attachment_transfer",
        arrayOf("size", "mime", "transport_policy", "expires_ms", "complete", "metadata"),
        "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction=?",
        arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash, direction), null, null, null).use { cursor ->
        if (!cursor.moveToFirst() || cursor.isNull(5)) return@use null
        val clear = storage.decryptPayload(cursor.getBlob(5), "personal_attachment_transfer",
            metadataPrimary(peerId, runId, reply, recordsHash, hash, direction))
        try {
            val actual = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
            val expected = attachmentMetadata(peerId, runId, reply, recordsHash, hash, direction, cursor.getInt(0),
                cursor.getString(1), cursor.getString(2), cursor.getLong(3), cursor.getInt(4) == 1)
            val base = if ("acked_chunks" in actual) {
                val chunks = expected.long("total_chunks").toInt()
                check(direction == "outgoing" && expected.string("transport_policy").startsWith("connection_only:") &&
                    chunks in 1..47 && actual.long("acked_chunks") in 1L until (1L shl chunks))
                JsonObject(actual - "acked_chunks")
            } else actual
            if (base != expected) throw TelefonProtokollFehler("Manipulierte Attachment-Metadaten.")
            actual
        } finally { clear.fill(0) }
    }

    fun snapshotOutgoingAttachment(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                   hash: String, mime: String, bytes: ByteArray, transportPolicy: String,
                                   expiresMs: Long) {
        require(bytes.size in 1..AnhangPruefung.ROH_MAX && transportPolicy in setOf("any", "wifi_only") &&
            AnhangPruefung.mime(bytes) == mime && sha256(bytes) == hash)
        var offset = 0
        while (offset < bytes.size) {
            val index = offset / PersonalSyncProtokoll.CHUNK_RAW
            val chunk = bytes.copyOfRange(offset, minOf(bytes.size, offset + PersonalSyncProtokoll.CHUNK_RAW))
            stageAttachmentChunk(peerId, runId, reply, recordsHash, hash, bytes.size, mime, index, chunk,
                "outgoing", transportPolicy, expiresMs)
            chunk.fill(0); offset += PersonalSyncProtokoll.CHUNK_RAW
        }
    }

    /** A legacy WLAN run becomes visible only with its complete initial outbox. */
    internal fun queueInitialAutoRun(peerId: String, message: JsonObject, batches: List<JsonObject>,
        attachments: List<Triple<String, String, ByteArray>> = emptyList(), attachmentExpiresMs: Long = message.long("expires_ms")) {
        TelefonNachrichten.validate(message)
        val request = message.getValue("body") as JsonObject
        require(message.string("kind") == "personal_sync.request" && request.string("trigger") == "auto_wifi")
        val runId = request.string("run_id")
        val format = request.long("format")
        require(batches.isNotEmpty() && (format >= 2 || attachments.isEmpty()))
        val now = System.currentTimeMillis()
        require(message.long("expires_ms") > now)
        helper.writableDatabase.inTransaction {
            rememberPersonalRunInDatabase(this, peerId, request, message.long("expires_ms"), now)
            val policy = requireNotNull(authenticatedRun(peerId, runId, this)).first.transportPolicy
            if (format >= 2) {
                queueFormat2DirectionIn(this, peerId, runId, false, batches.first().string("records_hash"), null,
                    batches, attachments, policy, attachmentExpiresMs)
                writableInsert(peerId, message, this, policy)
            } else {
                writableInsert(peerId, message, this, policy)
                batches.forEach { batch -> writableInsert(peerId,
                    TelefonNachrichten.message("personal_sync.batch", batch, 86_400_000), this, policy) }
            }
        }
    }

    fun queueFormat2Direction(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                              request: JsonObject?, batches: List<JsonObject>,
                              attachments: List<Triple<String, String, ByteArray>>, transportPolicy: String,
                              expiresMs: Long) {
        require(transportPolicy in setOf("any", "wifi_only"))
        helper.writableDatabase.inTransaction {
            queueFormat2DirectionIn(this, peerId, runId, reply, recordsHash, request, batches, attachments, transportPolicy, expiresMs)
        }
    }

    private fun queueFormat2DirectionIn(db: SQLiteDatabase, peerId: String, runId: String, reply: Boolean,
        recordsHash: String, request: JsonObject?, batches: List<JsonObject>,
        attachments: List<Triple<String, String, ByteArray>>, transportPolicy: String, expiresMs: Long,
        connectionBatches: List<JsonObject>? = null) = with(db) {
            attachments.forEach { (hash, mime, bytes) ->
                require(bytes.isNotEmpty() && bytes.size <= AnhangPruefung.ROH_MAX &&
                    AnhangPruefung.mime(bytes) == mime && sha256(bytes) == hash)
                var offset = 0
                while (offset < bytes.size) {
                    val index = offset / PersonalSyncProtokoll.CHUNK_RAW
                    val chunk = bytes.copyOfRange(offset, minOf(bytes.size, offset + PersonalSyncProtokoll.CHUNK_RAW))
                    stageAttachmentChunkIn(this, peerId, runId, reply, recordsHash, hash, bytes.size, mime,
                        index, chunk, "outgoing", transportPolicy, expiresMs)
                    chunk.fill(0); offset += PersonalSyncProtokoll.CHUNK_RAW
                }
            }
            request?.let { writableInsert(peerId, TelefonNachrichten.message("personal_sync.request", it, 3_600_000), this, transportPolicy) }
            (connectionBatches ?: batches.map { TelefonNachrichten.message("personal_sync.batch", it, 86_400_000) }).forEach { message ->
                writableInsert(peerId, message, this, transportPolicy)
            }
        }

    fun registerIncomingAttachment(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                   hash: String, size: Int, mime: String, transportPolicy: String,
                                   expiresMs: Long) {
        require(size in 1..AnhangPruefung.ROH_MAX && transportPolicy in setOf("any", "wifi_only"))
        registerIncomingAttachmentIn(peerId, runId, reply, recordsHash, hash, size, mime, transportPolicy, expiresMs)
    }

    private fun registerIncomingAttachmentIn(peerId: String, runId: String, reply: Boolean, recordsHash: String,
        hash: String, size: Int, mime: String, transportPolicy: String, expiresMs: Long) {
        require(size in 1..AnhangPruefung.ROH_MAX)
        val values = ContentValues().apply {
            put("peer_id", peerId); put("run_id", runId); put("reply", if (reply) 1 else 0)
            put("records_hash", recordsHash); put("sha256", hash); put("direction", "incoming")
            put("size", size); put("mime", mime); put("transport_policy", transportPolicy)
            put("expires_ms", expiresMs); put("complete", 0)
            putAuthenticatedMetadata(this, peerId, runId, reply, recordsHash, hash, "incoming", size, mime,
                transportPolicy, expiresMs)
        }
        helper.writableDatabase.inTransaction {
            val authenticated = authenticatedTransfer(peerId, runId, reply, recordsHash, hash, "incoming")
            if (authenticated == null) phoneCapacity("personal_attachment_transfer", values.getAsByteArray("metadata").size, 4096)
            if (authenticated != null && (authenticated.long("size") != size.toLong() ||
                authenticated.string("mime") != mime || authenticated.string("transport_policy") != transportPolicy))
                throw TelefonProtokollFehler("Widersprüchliches Attachment-Manifest.")
            query("personal_attachment_transfer", arrayOf("size", "mime", "transport_policy"),
                "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='incoming'",
                arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash), null, null, null).use {
                if (it.moveToFirst() && (it.getInt(0) != size || it.getString(1) != mime || it.getString(2) != transportPolicy))
                    throw TelefonProtokollFehler("Widersprüchliches Attachment-Manifest.")
            }
            insertWithOnConflict("personal_attachment_transfer", null, values, SQLiteDatabase.CONFLICT_IGNORE)
        }
    }

    fun stageIncomingAttachmentChunk(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                      hash: String, size: Int, mime: String, index: Int, bytes: ByteArray,
                                      transportPolicy: String, expiresMs: Long) {
        require(transportPolicy in setOf("any", "wifi_only"))
        stageAttachmentChunk(peerId, runId, reply, recordsHash, hash, size, mime, index, bytes,
            "incoming", transportPolicy, expiresMs)
    }

    private fun stageAttachmentChunk(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                     hash: String, size: Int, mime: String, index: Int, bytes: ByteArray,
                                     direction: String, policy: String, expiresMs: Long) {
        helper.writableDatabase.inTransaction { stageAttachmentChunkIn(this, peerId, runId, reply, recordsHash,
            hash, size, mime, index, bytes, direction, policy, expiresMs) }
    }

    private fun stageAttachmentChunkIn(db: SQLiteDatabase, peerId: String, runId: String, reply: Boolean,
                                       recordsHash: String, hash: String, size: Int, mime: String, index: Int,
                                       bytes: ByteArray, direction: String, policy: String, expiresMs: Long) = with(db) {
        val count = (size + PersonalSyncProtokoll.CHUNK_RAW - 1) / PersonalSyncProtokoll.CHUNK_RAW
        require(size in 1..AnhangPruefung.ROH_MAX && index in 0 until count &&
            (policy in setOf("any", "wifi_only") || policy.startsWith("connection_only:")) &&
            bytes.size == if (index + 1 < count) PersonalSyncProtokoll.CHUNK_RAW else size - index * PersonalSyncProtokoll.CHUNK_RAW)
        val primary = attachmentPrimary(peerId, runId, reply, recordsHash, hash, index, direction)
        val encrypted = storage.encryptPayload(bytes, "personal_attachment_chunk", primary)
        run {
            fun scalar(sql: String, args: Array<String> = emptyArray()): Long = rawQuery(sql, args).use { it.moveToFirst(); it.getLong(0) }
            val transferExists = scalar("SELECT COUNT(*) FROM personal_attachment_transfer WHERE peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction=?",
                arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash, direction)) > 0
            if (!transferExists) phoneCapacity("personal_attachment_transfer", rows = 4096)
            if (transferExists) {
                val authenticated = authenticatedTransfer(peerId, runId, reply, recordsHash, hash, direction, this)
                    ?: throw TelefonProtokollFehler("Nicht authentifizierte Attachment-Metadaten.")
                if (authenticated.long("size") != size.toLong() || authenticated.string("mime") != mime ||
                    authenticated.string("transport_policy") != policy)
                    throw TelefonProtokollFehler("Widersprüchliche Attachment-Metadaten.")
            }
            if (!transferExists && (scalar("SELECT COUNT(DISTINCT run_id||':'||reply||':'||direction) FROM personal_attachment_transfer WHERE peer_id=?", arrayOf(peerId)) >= 4 ||
                scalar("SELECT COUNT(DISTINCT sha256) FROM personal_attachment_transfer WHERE peer_id=? AND run_id=?", arrayOf(peerId, runId)) >= 256) ||
                scalar("SELECT COUNT(*) FROM personal_attachment_chunk") >= 4096 ||
                scalar("SELECT COALESCE(SUM(length(payload)),0) FROM personal_attachment_chunk") + encrypted.size > 100L * 1024 * 1024 ||
                scalar("SELECT COALESCE(SUM(length(payload)),0) FROM personal_attachment_chunk WHERE peer_id=? AND run_id=?", arrayOf(peerId, runId)) + encrypted.size > 50L * 1024 * 1024)
                throw TelefonProtokollFehler("Attachment-Staging ist voll.")
            val transfer = ContentValues().apply { put("peer_id", peerId); put("run_id", runId); put("reply", if (reply) 1 else 0)
                put("records_hash", recordsHash); put("sha256", hash); put("direction", direction); put("size", size)
                put("mime", mime); put("transport_policy", policy); put("expires_ms", expiresMs); put("complete", 0)
                putAuthenticatedMetadata(this, peerId, runId, reply, recordsHash, hash, direction, size, mime, policy, expiresMs) }
            insertWithOnConflict("personal_attachment_transfer", null, transfer, SQLiteDatabase.CONFLICT_IGNORE)
            query("personal_attachment_chunk", arrayOf("payload"),
                "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction=? AND chunk_index=?",
                arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash, direction, index.toString()), null, null, null).use {
                if (it.moveToFirst()) {
                    val old = storage.decryptPayload(it.getBlob(0), "personal_attachment_chunk", primary)
                    if (!old.contentEquals(bytes)) throw TelefonProtokollFehler("Widersprüchlicher Attachment-Chunk.")
                    return@with
                }
            }
            val chunk = ContentValues(transfer).apply { remove("size"); remove("mime"); remove("transport_policy"); remove("expires_ms"); remove("complete"); remove("metadata")
                put("chunk_index", index); put("payload", encrypted) }
            insertOrThrow("personal_attachment_chunk", null, chunk)
        }
    }

    fun missingAttachmentRanges(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                hash: String): List<List<Int>> {
        val size = authenticatedTransfer(peerId, runId, reply, recordsHash, hash, "incoming")
            ?.long("size")?.toInt() ?: return emptyList()
        val present = mutableSetOf<Int>()
        helper.readableDatabase.query("personal_attachment_chunk", arrayOf("chunk_index"),
            "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='incoming'",
            arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash), null, null, null).use {
            while (it.moveToNext()) present += it.getInt(0) }
        val ranges = mutableListOf<MutableList<Int>>()
        repeat((size + PersonalSyncProtokoll.CHUNK_RAW - 1) / PersonalSyncProtokoll.CHUNK_RAW) { index -> if (index !in present) {
            if (ranges.lastOrNull()?.get(1) == index) ranges.last()[1]++ else ranges += mutableListOf(index, index + 1)
        } }
        return ranges
    }

    internal fun requestedAttachmentChunks(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                  wants: List<Pair<String, List<List<Int>>>>,
                                  transport: TelefonTransportArt): List<Triple<String, Int, ByteArray>> {
        val result = mutableListOf<Triple<String, Int, ByteArray>>()
        wants.forEach { (hash, ranges) ->
            val policy = authenticatedTransfer(peerId, runId, reply, recordsHash, hash, "outgoing")
                ?.string("transport_policy")
            if (policy !in setOf("any", "wifi_only") || policy == "wifi_only" && transport != TelefonTransportArt.WIFI) return@forEach
            ranges.forEach { range -> (range[0] until range[1]).forEach { index ->
                val raw = readOutgoingAttachmentChunk(peerId, runId, reply, recordsHash, hash, index)
                if (raw != null) result += Triple(hash, index, raw)
                if (result.size == 8) return result
            } }
        }
        return result
    }

    private fun readOutgoingAttachmentChunk(peerId: String, runId: String, reply: Boolean, recordsHash: String, hash: String,
        index: Int): ByteArray? = helper.readableDatabase.query("personal_attachment_chunk", arrayOf("payload"),
        "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing' AND chunk_index=?",
        arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash, index.toString()), null, null, null).use { row ->
        if (!row.moveToFirst()) return@use null
        storage.decryptPayload(row.getBlob(0), "personal_attachment_chunk",
            attachmentPrimary(peerId, runId, reply, recordsHash, hash, index, "outgoing"))
    }

    internal fun incomingAttachmentComplete(peerId: String, runId: String, reply: Boolean,
                                            recordsHash: String, hash: String): Boolean =
        authenticatedTransfer(peerId, runId, reply, recordsHash, hash, "incoming")?.get("complete") == JsonPrimitive(true)

    fun verifyIncomingAttachment(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                 hash: String, output: OutputStream): Boolean {
        if (missingAttachmentRanges(peerId, runId, reply, recordsHash, hash).isNotEmpty()) return false
        val digest = MessageDigest.getInstance("SHA-256"); var total = 0; val prefix = mutableListOf<Byte>()
        val transfer = authenticatedTransfer(peerId, runId, reply, recordsHash, hash, "incoming") ?: return false
        val expected = transfer.long("size").toInt() to transfer.string("mime")
        helper.readableDatabase.query("personal_attachment_chunk", arrayOf("chunk_index", "payload"),
            "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='incoming'",
            arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash), null, null, "chunk_index").use { rows ->
            while (rows.moveToNext()) {
                val index = rows.getInt(0); val primary = attachmentPrimary(peerId, runId, reply, recordsHash, hash, index, "incoming")
                val raw = storage.decryptPayload(rows.getBlob(1), "personal_attachment_chunk", primary)
                raw.take(16 - prefix.size).forEach(prefix::add); digest.update(raw); output.write(raw); total += raw.size; raw.fill(0)
            }
        }
        val valid = total == expected.first && digest.digest().joinToString("") { "%02x".format(it) } == hash &&
            AnhangPruefung.mime(prefix.toByteArray()) == expected.second
        if (valid) helper.writableDatabase.update("personal_attachment_transfer", ContentValues().apply {
            put("complete", 1); putAuthenticatedMetadata(this, peerId, runId, reply, recordsHash, hash, "incoming",
                expected.first, expected.second, transfer.string("transport_policy"), transfer.long("expires_ms"), true)
        }, "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='incoming'",
            arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash))
        return valid
    }

    fun completeOutgoingAttachment(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                   hash: String) {
        val transfer = authenticatedTransfer(peerId, runId, reply, recordsHash, hash, "outgoing")
        if (transfer?.string("transport_policy") !in setOf("any", "wifi_only"))
            throw TelefonProtokollFehler("Nicht authentifizierte Attachment-Metadaten.")
        helper.writableDatabase.inTransaction {
            delete("personal_attachment_chunk", "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing'",
                arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash))
            delete("personal_attachment_transfer", "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing'",
                arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash))
        }
    }

    private fun hasAuthenticatedOutgoingAttachments(peerId: String, runId: String,
        pendingOnly: Boolean = false, db: SQLiteDatabase = helper.readableDatabase): Boolean {
        var found = false
        db.query("personal_attachment_transfer",
            arrayOf("reply", "records_hash", "sha256", "direction"), "peer_id=? AND run_id=?",
            arrayOf(peerId, runId), null, null, null).use { cursor -> while (cursor.moveToNext()) {
            val reply = cursor.getInt(0) == 1; val recordsHash = cursor.getString(1)
            val hash = cursor.getString(2); val direction = cursor.getString(3)
            val transfer = authenticatedTransfer(peerId, runId, reply, recordsHash, hash, direction, db)
                ?: throw TelefonProtokollFehler("Nicht authentifizierte Attachment-Metadaten.")
            if (direction == "outgoing" && (!pendingOnly || transfer["complete"] == JsonPrimitive(false))) found = true
        } }
        return found
    }

    private fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    fun stagePersonalBatch(peerId: String, message: JsonObject, now: Long = System.currentTimeMillis()): List<JsonObject>? {
        val body = message["body"] as JsonObject
        val runId = body.string("run_id"); val reply = if ((body["reply"] as JsonPrimitive).content.toBooleanStrict()) 1 else 0
        val sequence = body.long("sequence").toInt(); if (sequence !in 0 until 4096) throw TelefonProtokollFehler("Ungültige Personal-Sync-Sequenz.")
        val primary = "$peerId:$runId:$reply:$sequence"
        val encrypted = storage.encryptPayload(TelefonKanonisch.bytes(message), "personal_batch", primary)
        val rows = helper.writableDatabase.inTransaction {
            val exists = query("personal_batch", arrayOf("message_id"),
                "peer_id=? AND run_id=? AND reply=? AND sequence=?", arrayOf(peerId, runId, reply.toString(), sequence.toString()),
                null, null, null).use { it.moveToFirst() }
            if (!exists) {
                phoneCapacity("personal_batch", encrypted.size, 4096)
                phoneCapacity("inbox", encrypted.size)
                phoneCapacity("dedupe", rows = 100_000)
            }
            query("personal_batch", arrayOf("batch_id", "message_id", "payload", "last"),
                "peer_id=? AND run_id=? AND reply=? AND sequence=?", arrayOf(peerId, runId, reply.toString(), sequence.toString()),
                null, null, null).use { cursor ->
                if (cursor.moveToFirst()) {
                    val clear = storage.decryptPayload(cursor.getBlob(2), "personal_batch", primary)
                    try {
                        val previous = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                        if (cursor.getString(0) != body.string("batch_id") || cursor.getString(1) != message.string("message_id") ||
                            cursor.getInt(3) != (if ((body["last"] as JsonPrimitive).content.toBooleanStrict()) 1 else 0) || previous != message)
                            throw TelefonProtokollFehler("Widersprüchliche Personal-Sync-Sequenz.")
                    } finally { clear.fill(0) }
                }
            }
            val values = ContentValues().apply {
                put("peer_id", peerId); put("run_id", runId); put("reply", reply); put("sequence", sequence)
                put("batch_id", body.string("batch_id")); put("message_id", message.string("message_id")); put("received_ms", now)
                put("expires_ms", message.long("expires_ms")); put("payload", encrypted)
                put("last", if ((body["last"] as JsonPrimitive).content.toBooleanStrict()) 1 else 0)
            }
            insertWithOnConflict("personal_batch", null, values, SQLiteDatabase.CONFLICT_IGNORE)
            val inboxPayload = storage.encryptPayload(TelefonKanonisch.bytes(message), "inbox", message.string("message_id"))
            val inbox = ContentValues().apply {
                put("message_id", message.string("message_id")); put("peer_id", peerId); put("kind", message.string("kind"))
                put("received_ms", now); put("expires_ms", message.long("expires_ms")); put("payload", inboxPayload); put("state", "staged")
            }
            insertWithOnConflict("inbox", null, inbox, SQLiteDatabase.CONFLICT_IGNORE)
            val dedupe = ContentValues().apply {
                put("message_id", message.string("message_id")); put("peer_id", peerId)
                put("result", "accepted"); put("error", "none"); put("seen_ms", now)
            }
            insertWithOnConflict("dedupe", null, dedupe, SQLiteDatabase.CONFLICT_IGNORE)
            val result = mutableListOf<Triple<Int, ByteArray, Int>>()
            query("personal_batch", arrayOf("sequence", "payload", "last"), "peer_id=? AND run_id=? AND reply=?",
                arrayOf(peerId, runId, reply.toString()), null, null, "sequence", "4097").use { cursor ->
                while (cursor.moveToNext()) result += Triple(cursor.getInt(0), cursor.getBlob(1), cursor.getInt(2))
            }
            if (result.size > 4096 || result.sumOf { it.second.size.toLong() } > 50L * 1024 * 1024)
                throw TelefonProtokollFehler("Personal-Sync-Lauf ist zu groß.")
            val finals = result.filter { it.third == 1 }.map { it.first }
            if (finals.size > 1 || finals.singleOrNull()?.let { final -> result.any { it.first > final } } == true)
                throw TelefonProtokollFehler("Widersprüchliche Personal-Sync-Endsequenz.")
            var recordCount = 0
            result.forEach { (index, payload, _) ->
                val clear = storage.decryptPayload(payload, "personal_batch", "$peerId:$runId:$reply:$index")
                try {
                    val staged = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                    recordCount += ((staged["body"] as JsonObject)["records"] as JsonArray).size
                } finally { clear.fill(0) }
            }
            if (recordCount > 100_000) throw TelefonProtokollFehler("Personal-Sync-Lauf ist zu groß.")
            result
        }
        if (rows.size > 4096) throw TelefonProtokollFehler("Zu viele Personal-Sync-Pakete.")
        val last = rows.filter { it.third == 1 }.map { it.first }
        if (last.size != 1 || rows.map { it.first } != (0..last.single()).toList()) return null
        var records = 0; var bytes = 0
        return rows.map { (index, payload, _) ->
            bytes += payload.size
            val clear = storage.decryptPayload(payload, "personal_batch", "$peerId:$runId:$reply:$index")
            try { (TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject).also {
                records += (((it["body"] as JsonObject)["records"] as JsonArray).size)
            } } finally { clear.fill(0) }
        }.also { batches ->
            if (records > 100_000 || bytes > 50 * 1024 * 1024) throw TelefonProtokollFehler("Personal-Sync-Lauf ist zu groß.")
            val finalBody = batches.last()["body"] as JsonObject
            if (finalBody.long("format") >= 2L) {
                val hashes = batches.map { ((it["body"] as JsonObject)["records_hash"] as JsonPrimitive).content }.toSet()
                val all = batches.flatMap { PersonalSyncProtokoll.decodeBatch(it["body"] as JsonObject) }
                if (hashes.size != 1 || io.gitlab.maik3531.magnolienotes.daten.PersonalSync.recordsHash(all) != hashes.single())
                    throw TelefonProtokollFehler("Widersprüchlicher Records-Hash.")
            }
        }
    }

    fun finishPersonalBatch(peerId: String, runId: String, reply: Boolean) {
        helper.writableDatabase.delete("personal_batch", "peer_id=? AND run_id=? AND reply=?",
            arrayOf(peerId, runId, if (reply) "1" else "0"))
    }

    fun readyPersonalBatches(peerId: String? = null, runId: String? = null): List<Pair<String, List<JsonObject>>> {
        require((peerId == null) == (runId == null))
        val groups = mutableListOf<Triple<String, String, Int>>()
        val selection = if (peerId == null) null else "peer_id=? AND run_id=?"
        val args = if (peerId == null) null else arrayOf(peerId, checkNotNull(runId))
        helper.readableDatabase.query(true, "personal_batch", arrayOf("peer_id", "run_id", "reply"), selection, args,
            null, null, null, null).use { while (it.moveToNext()) groups += Triple(it.getString(0), it.getString(1), it.getInt(2)) }
        return groups.mapNotNull { (peerId, runId, reply) ->
            val rows = mutableListOf<Triple<Int, ByteArray, Int>>()
            helper.readableDatabase.query("personal_batch", arrayOf("sequence", "payload", "last"),
                "peer_id=? AND run_id=? AND reply=?", arrayOf(peerId, runId, reply.toString()), null, null, "sequence").use {
                while (it.moveToNext()) rows += Triple(it.getInt(0), it.getBlob(1), it.getInt(2))
            }
            val lasts = rows.filter { it.third == 1 }.map { it.first }
            if (lasts.size != 1 || rows.map { it.first } != (0..lasts.single()).toList()) null else peerId to rows.map { (sequence, payload, _) ->
                val clear = storage.decryptPayload(payload, "personal_batch", "$peerId:$runId:$reply:$sequence")
                try { TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject }
                finally { clear.fill(0) }
            }
        }
    }

    fun rememberPersonalRun(peerId: String, body: JsonObject, wireExpiresMs: Long,
                             now: Long = System.currentTimeMillis(), actorRun: Boolean = false) {
        rememberPersonalRunInDatabase(helper.writableDatabase, peerId, body, wireExpiresMs, now, actorRun)
    }

    private fun rememberPersonalRunInDatabase(db: SQLiteDatabase, peerId: String, body: JsonObject,
                                              wireExpiresMs: Long, now: Long, actorRun: Boolean = false,
                                              connectionBound: Boolean = false) {
        val runId = body.string("run_id"); val key = "personal_run:$peerId:$runId"
        val trigger = body.string("trigger")
        require(connectionBound == (trigger == PersonalAutoSync.CONNECTION)) { "Missing or unexpected connection run authority" }
        if (actorRun) require(trigger == "manual") { "Actor runs are explicit manual operations" }
        db.inTransaction {
            val existing = authenticatedRun(peerId, runId, this)
            if (existing != null) {
                require(existing.first.actor == actorRun) { "Cannot reinterpret actor and ordinary runs" }
                if (existing.second != body) throw TelefonProtokollFehler("Widersprüchlicher Personal-Sync-Lauf.")
                val expires = PersonalRunAuthentication.effectiveExpiry(wireExpiresMs, now, existing.first.expiresMs)
                if (expires != existing.first.expiresMs) updatePersonalRun(this, peerId, runId, allowExpired = true) {
                    it.copy(expiresMs = expires)
                }
                return@inTransaction
            }
            val index = PersonalRunIndex(peerId, runId, trigger, PersonalAutoSync.policy(trigger),
                now, PersonalRunAuthentication.effectiveExpiry(wireExpiresMs, now), actor = actorRun)
            val encrypted = storage.encryptPayload(TelefonKanonisch.bytes(runEnvelope(index, body)),
                "personal_run", key)
            phoneCapacity("personal_run", encrypted.size, 1024)
            val values = ContentValues().apply {
                put("peer_id", peerId); put("run_id", runId); put("trigger", trigger)
                put("transport_policy", index.transportPolicy); put("payload", encrypted)
                put("created_ms", index.createdMs); put("expires_ms", index.expiresMs)
            }
            insertOrThrow("personal_run", null, values)
        }
    }

    private fun contentPolicyHash(settings: JsonObject): String {
        require(SharedSyncSettings.effective(settings)["content_mode"] == JsonPrimitive("phone_scope"))
        val fields = settings.getValue("settings") as JsonObject
        return MessageDigest.getInstance("SHA-256").digest(TelefonKanonisch.bytes(fields.getValue("content_mode") as JsonObject))
            .joinToString("") { "%02x".format(it.toInt() and 255) }
    }

    private fun readScopeRun(db: SQLiteDatabase, peerId: String, runId: String): JsonObject? {
        val key = "personal_scope:$peerId:$runId"
        return db.query("meta", arrayOf("value"), "key=?", arrayOf(key), null, null, null).use {
            if (!it.moveToFirst()) return@use null
            val clear = storage.decryptPayload(it.getBlob(0), "personal_scope", key)
            try {
                val value = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                val local = value.containsKey("request_message_id")
                TelefonNachrichten.exact(value, setOf("peer_key", "local_actor", "scope", "content_policy", "restore_epoch") +
                    (if (local) setOf("request_message_id", "request_accepted") else emptySet()) +
                    (if ("connection_authority" in value) setOf("connection_authority") else emptySet()) +
                    value.keys.intersect(setOf("initial_batches", "reply_results", "received_report_id")))
                value["connection_authority"]?.let { require(Regex("[0-9a-f]{64}").matches(value.string("connection_authority"))) }
                value["initial_batches"]?.let { batches ->
                    require(local && "connection_authority" in value && batches is JsonObject && batches.isNotEmpty())
                    for ((id, receipt) in batches) {
                        TelefonNachrichten.uuid4(id)
                        require(receipt in setOf(JsonPrimitive(true), JsonPrimitive(false)))
                    }
                }
                value["reply_results"]?.let { results ->
                    require("initial_batches" in value && results is JsonObject)
                    for ((id, receipt) in results) {
                        TelefonNachrichten.uuid4(id)
                        require(receipt in setOf(JsonPrimitive(true), JsonPrimitive(false)))
                    }
                }
                value["received_report_id"]?.let {
                    require("reply_results" in value)
                    TelefonNachrichten.uuid4(value.string("received_report_id"))
                }
                if (local) {
                    TelefonNachrichten.uuid4(value.string("request_message_id"))
                    require(value["request_accepted"] in setOf(JsonPrimitive(true), JsonPrimitive(false)))
                }
                PhoneContentScope.validateReference(value.getValue("scope") as JsonObject)
                value
            } finally { clear.fill(0) }
        }
    }

    internal fun rememberScopedRun(binding: SharedSettingsBinding, shared: SharedSyncStorage, request: JsonObject,
                                    reference: JsonObject, wireExpiresMs: Long, now: Long = System.currentTimeMillis(),
                                    actorRun: Boolean = false, connectionAuthority: String? = null) {
        PersonalSyncProtokoll.validate("personal_sync.request", request); PhoneContentScope.validateReference(reference)
        val connection = request.string("trigger") == PersonalAutoSync.CONNECTION
        require(connection == (connectionAuthority != null))
        require(connectionAuthority == null || !actorRun && Regex("[0-9a-f]{64}").matches(connectionAuthority))
        require(request.long("format") in setOf(3L, 14L) && wireExpiresMs > now)
        val runId = request.string("run_id"); val peerId = binding.peerActor; val key = "personal_scope:$peerId:$runId"
        shared.withWriteTransaction(binding) {
            val settings = requireNotNull(shared.read(binding))
            val policyHash = contentPolicyHash(settings)
            val marker = buildJsonObject {
                put("peer_key", JsonPrimitive(binding.peerPublic)); put("local_actor", JsonPrimitive(binding.localActor))
                put("scope", reference); put("content_policy", JsonPrimitive(policyHash)); put("restore_epoch", JsonPrimitive(restoreEpoch()))
                if (connectionAuthority != null) put("connection_authority", JsonPrimitive(connectionAuthority))
            }
            val existing = authenticatedRun(peerId, runId, this)
            val oldScope = readScopeRun(this, peerId, runId)
            require((existing == null) == (oldScope == null)) { "Cannot change between legacy and scoped run" }
            if (existing != null) {
                require(existing.first.actor == actorRun) { "Cannot reinterpret actor and ordinary scoped runs" }
                if (connection) check(oldScope?.get("connection_authority") == marker["connection_authority"]) {
                    "Connection request belongs to another reader"
                }
                require(existing.second == request && oldScope == marker && existing.first.expiresMs > now && wireExpiresMs <= existing.first.expiresMs)
                return@withWriteTransaction
            }
            rememberPersonalRunInDatabase(this, peerId, request, wireExpiresMs, now, actorRun, connection)
            val clear = TelefonKanonisch.bytes(marker)
            val sealed = try { storage.encryptPayload(clear, "personal_scope", key) } finally { clear.fill(0) }
            insertOrThrow("meta", null, ContentValues().apply { put("key", key); put("value", sealed) })
            check(policyHash == contentPolicyHash(requireNotNull(shared.read(binding))))
            shared.requireWritable(binding)
        }
    }

    internal fun scopedRunReference(binding: SharedSettingsBinding, shared: SharedSyncStorage, runId: String,
                                    now: Long = System.currentTimeMillis()): JsonObject? {
        val marker = readScopeRun(helper.readableDatabase, binding.peerActor, runId) ?: return null
        shared.requireWritable(binding)
        val settings = requireNotNull(shared.read(binding))
        val run = authenticatedRun(binding.peerActor, runId)
        check(marker["peer_key"] == JsonPrimitive(binding.peerPublic) && marker["local_actor"] == JsonPrimitive(binding.localActor) &&
            marker["restore_epoch"] == JsonPrimitive(restoreEpoch()) && marker["content_policy"] == JsonPrimitive(contentPolicyHash(settings)) &&
            run != null && run.first.expiresMs > now) { "Scoped run is no longer current" }
        return marker.getValue("scope") as JsonObject
    }

    internal fun receiveScopedConnectionRequest(binding: SharedSettingsBinding, shared: SharedSyncStorage,
        message: JsonObject, reference: JsonObject, authority: String, requireCurrent: () -> Unit): Pair<String, String> =
        shared.withWriteTransaction(binding) {
            val request = message.getValue("body") as JsonObject
            check(message.string("kind") == "personal_sync.request" && request.string("trigger") == PersonalAutoSync.CONNECTION)
            rememberScopedRun(binding, shared, request, reference, message.long("expires_ms"), connectionAuthority = authority)
            requireCurrent()
            receive(binding.peerActor, message).also { result ->
                check(result.first in setOf("accepted", "duplicate")) { "Connection request receipt was not accepted" }
                requireCurrent()
            }
        }

    internal fun scopedConnectionAuthority(binding: SharedSettingsBinding, shared: SharedSyncStorage, runId: String): String? {
        if (scopedRunReference(binding, shared, runId) == null) return null
        return (readScopeRun(helper.readableDatabase, binding.peerActor, runId)?.get("connection_authority") as? JsonPrimitive)?.content
    }

    private fun connectionPolicy(marker: JsonObject, runId: String): String =
        "connection_only:${marker.string("connection_authority")}:$runId"

    private fun connectionInitialBatchesAccepted(marker: JsonObject): Boolean =
        marker["request_accepted"] == JsonPrimitive(true) &&
            (marker["initial_batches"] as? JsonObject)?.values?.all { it == JsonPrimitive(true) } == true

    internal fun connectionReceivesDirection(peerId: String, runId: String, reply: Boolean): Boolean =
        readScopeRun(helper.readableDatabase, peerId, runId)?.let { marker ->
            "connection_authority" in marker && reply == ("request_message_id" in marker)
        } == true

    internal fun connectionAllowsIncomingBatch(peerId: String, runId: String, reply: Boolean): Boolean =
        connectionAllowsIncomingBatch(helper.readableDatabase, peerId, runId, reply)

    private fun connectionAllowsIncomingBatch(db: SQLiteDatabase, peerId: String, runId: String, reply: Boolean): Boolean {
        val marker = readScopeRun(db, peerId, runId) ?: return false
        if (!reply) return "request_message_id" !in marker
        return connectionInitialBatchesAccepted(marker) && !hasAuthenticatedOutgoingAttachments(peerId, runId, pendingOnly = true, db = db)
    }

    internal fun recordConnectionReplySaved(binding: SharedSettingsBinding, shared: SharedSyncStorage, request: JsonObject,
                                            authority: String, staged: List<JsonObject>, hashes: Set<String>, requireSaved: () -> Unit) {
        val peerId = binding.peerActor
        val runId = request.string("run_id")
        shared.withWriteTransaction(binding) {
            requireSaved()
            val (run, stored) = checkNotNull(authenticatedRun(peerId, runId, this))
            check(stored == request && run.transportPolicy == "connection_only" && !run.reported &&
                run.expiresMs > System.currentTimeMillis() && scopedConnectionAuthority(binding, shared, runId) == authority &&
                connectionAllowsIncomingBatch(this, peerId, runId, reply = true))
            check(staged.isNotEmpty() && staged.all { it.getValue("body").jsonObject["reply"] == JsonPrimitive(true) } &&
                readyPersonalBatches(peerId, runId).single().second == staged)
            val aggregate = staged.last().getValue("body").jsonObject.string("records_hash")
            val marker = checkNotNull(readScopeRun(this, peerId, runId))
            check("reply_results" !in marker)
            val results = writeConnectionIncomingResults(this, peerId, runId, true, authority, aggregate, hashes, run.expiresMs)
            writeScopeMarker(this, peerId, runId, JsonObject(marker + ("reply_results" to
                JsonObject(results.associateWith { JsonPrimitive(false) }))))
            updatePersonalRun(this, peerId, runId) { it.copy(appliedReply = true) }
            requireSaved()
        }
    }

    private fun requireConnectionReport(db: SQLiteDatabase, peerId: String, message: JsonObject, authority: String): JsonObject {
        val report = message.getValue("body").jsonObject
        val runId = report.string("run_id")
        val (run, request) = checkNotNull(authenticatedRun(peerId, runId, db))
        val marker = checkNotNull(readScopeRun(db, peerId, runId))
        val receipt = marker["received_report_id"]
        val now = System.currentTimeMillis()
        check(message.string("kind") == "personal_sync.report" && report["format"] == request["format"] &&
            report["trigger"] == request["trigger"] && report["state"] == JsonPrimitive("complete") &&
            report["error"] == JsonPrimitive("none") && message.long("expires_ms") > now && run.expiresMs > now &&
            run.transportPolicy == "connection_only" && run.appliedReply &&
            marker["connection_authority"] == JsonPrimitive(authority) &&
            marker["restore_epoch"] == JsonPrimitive(restoreEpoch()) &&
            (marker["reply_results"] as? JsonObject)?.values?.all { it == JsonPrimitive(true) } == true &&
            (receipt == message["message_id"] || receipt == null && !run.reported))
        return marker
    }

    internal fun receiveConnectionReport(binding: SharedSettingsBinding, shared: SharedSyncStorage, message: JsonObject,
                                         authority: String, requireCurrent: () -> Unit): Pair<String, String> =
        shared.withWriteTransaction(binding) {
            requireCurrent()
            val peerId = binding.peerActor
            val marker = requireConnectionReport(this, peerId, message, authority)
            val duplicate = "received_report_id" in marker
            if (duplicate) check(receivedMatches(peerId, message))
            val receipt = receive(peerId, message)
            check(receipt.first == if (duplicate) "duplicate" else "accepted")
            if (!duplicate) writeScopeMarker(this, peerId, message.getValue("body").jsonObject.string("run_id"),
                JsonObject(marker + ("received_report_id" to message.getValue("message_id"))))
            requireCurrent()
            receipt
        }

    internal fun confirmConnectionReportSent(binding: SharedSettingsBinding, shared: SharedSyncStorage, message: JsonObject,
                                             authority: String, requireCurrent: () -> Unit): Boolean =
        shared.withWriteTransaction(binding) {
            requireCurrent()
            val peerId = binding.peerActor
            val marker = requireConnectionReport(this, peerId, message, authority)
            check(marker["received_report_id"] == message["message_id"] && receivedMatches(peerId, message))
            val runId = message.getValue("body").jsonObject.string("run_id")
            if (authenticatedRun(peerId, runId, this)?.first?.reported == true) return@withWriteTransaction false
            updatePersonalRun(this, peerId, runId) { it.copy(reported = true) }
            delete("personal_batch", "peer_id=? AND run_id=? AND reply=1", arrayOf(peerId, runId))
            requireCurrent()
            true
        }

    private fun connectionInitialMarker(db: SQLiteDatabase, peerId: String, message: JsonObject, now: Long): JsonObject? {
        val kind = message.string("kind")
        val body = message.getValue("body").jsonObject
        if (kind != "personal_sync.request" && (kind != "personal_sync.batch" || body["reply"] != JsonPrimitive(false))) return null
        val runId = body.string("run_id")
        val (run, request) = authenticatedRun(peerId, runId, db) ?: return null
        val expiry = message.long("expires_ms")
        if (run.transportPolicy != "connection_only" || run.reported || expiry <= now || expiry > run.expiresMs)
            return null
        val marker = readScopeRun(db, peerId, runId) ?: return null
        val requestId = marker["request_message_id"] ?: return null
        if ("connection_authority" !in marker || marker["restore_epoch"] != JsonPrimitive(restoreEpoch())) return null
        if (kind == "personal_sync.request" && (requestId != message["message_id"] || body != request ||
                marker["request_accepted"] != JsonPrimitive(false))) return null
        if (kind == "personal_sync.batch") {
            if ((marker["initial_batches"] as? JsonObject)?.get(message.string("message_id")) != JsonPrimitive(false)) return null
            PersonalSyncProtokoll.validateBatchForRequest(request, body)
        }
        return marker
    }

    internal fun acknowledgeConnectionInitial(peerId: String, message: JsonObject, status: String, error: String): Boolean =
        helper.writableDatabase.inTransaction {
            val now = System.currentTimeMillis()
            val marker = connectionInitialMarker(this, peerId, message, now) ?: return@inTransaction false
            val id = message.string("message_id")
            val runId = message.getValue("body").jsonObject.string("run_id")
            val policy = connectionPolicy(marker, runId)
            val request = message.string("kind") == "personal_sync.request"
            if (!request && marker["request_accepted"] != JsonPrimitive(true)) return@inTransaction true
            val where = "peer_id=? AND message_id=? AND transport_policy=? AND attempts>0"
            val args = arrayOf(peerId, id, policy)
            if (outboxPersonalMessage(peerId, id) != message) return@inTransaction false
            if (status == "rejected" && error == "temporary_failure") return@inTransaction true
            if (delete("outbox", where, args) != 1) return@inTransaction true
            if (status in setOf("accepted", "duplicate")) {
                val receipt = if (request) "request_accepted" to JsonPrimitive(true)
                    else "initial_batches" to JsonObject(marker.getValue("initial_batches").jsonObject + (id to JsonPrimitive(true)))
                writeScopeMarker(this, peerId, runId, JsonObject(marker + receipt))
            } else {
                retireScopedRequests(this, peerId, setOf(runId))
            }
            true
        }

    private fun connectionCompletionPolicy(db: SQLiteDatabase, peerId: String, message: JsonObject, now: Long): String? {
        val kind = message.string("kind")
        val body = message.getValue("body") as JsonObject
        when (kind) {
            "personal_sync.batch" ->
                if (body["reply"] != JsonPrimitive(true)) return null
            "personal_sync.attachment_chunk" -> Unit
            "personal_sync.report" -> if (body["trigger"] != JsonPrimitive(PersonalAutoSync.CONNECTION)) return null
            "personal_sync.attachment_request", "personal_sync.attachment_result" -> Unit
            else -> return null
        }
        val runId = body.string("run_id")
        val run = authenticatedRun(peerId, runId, db)?.first ?: return null
        if (run.transportPolicy != "connection_only" || run.reported ||
            run.expiresMs <= now || message.long("expires_ms") > run.expiresMs) return null
        val attachmentRequest = kind == "personal_sync.attachment_request"
        val attachmentResult = kind == "personal_sync.attachment_result"
        val outgoingChunk = kind == "personal_sync.attachment_chunk"
        val initialChunk = outgoingChunk && body["reply"] == JsonPrimitive(false)
        val marker = readScopeRun(db, peerId, runId) ?: return null
        if ("connection_authority" !in marker) return null
        val incomingReply = (attachmentRequest || attachmentResult) && body["reply"] == JsonPrimitive(true)
        if (when {
                initialChunk -> !connectionInitialBatchesAccepted(marker)
                incomingReply -> !connectionAllowsIncomingBatch(db, peerId, runId, true) || run.appliedReply != attachmentResult ||
                    attachmentResult && (marker["reply_results"] as? JsonObject)?.get(message.string("message_id")) != JsonPrimitive(false)
                attachmentRequest -> run.appliedRequest || run.responded
                attachmentResult -> !run.appliedRequest
                else -> !run.appliedRequest || !run.responded
            }) return null
        val policy = connectionPolicy(marker, runId)
        if (attachmentRequest) {
            val want = (body["wants"] as? JsonArray)?.singleOrNull() as? JsonObject ?: return null
            val transfer = authenticatedTransfer(peerId, runId, incomingReply, body.string("records_hash"),
                want.string("sha256"), "incoming", db) ?: return null
            if (transfer["transport_policy"] != JsonPrimitive(policy) ||
                transfer.long("expires_ms") < message.long("expires_ms")) return null
        }
        if (attachmentResult) {
            val transfer = authenticatedTransfer(peerId, runId, incomingReply, body.string("records_hash"),
                body.string("sha256"), "incoming", db) ?: return null
            if (transfer["transport_policy"] != JsonPrimitive(policy) || transfer["complete"] != JsonPrimitive(true) ||
                body["state"] != JsonPrimitive("complete") || transfer.long("expires_ms") < message.long("expires_ms")) return null
        }
        if (outgoingChunk) {
            val transfer = authenticatedTransfer(peerId, runId, !initialChunk, body.string("records_hash"),
                body.string("sha256"), "outgoing", db) ?: return null
            if (transfer["transport_policy"] != JsonPrimitive(policy) || transfer["complete"] != JsonPrimitive(false) ||
                body.long("index") !in 0L until transfer.long("total_chunks") ||
                transfer.long("expires_ms") < message.long("expires_ms")) return null
        }
        if (kind == "personal_sync.report" && connectionCompletionPending(db, peerId, runId, policy)) return null
        return policy
    }

    internal fun receiveConnectionOutgoingWindow(binding: SharedSettingsBinding, shared: SharedSyncStorage,
        message: JsonObject, authority: String, requireCurrent: () -> Unit) {
        val body = message.getValue("body") as JsonObject
        check(message.string("kind") == "personal_sync.attachment_request")
        val reply = body.getValue("reply").jsonPrimitive.content.toBooleanStrict()
        val peerId = binding.peerActor
        val runId = body.string("run_id")
        val aggregate = body.string("records_hash")
        shared.withWriteTransaction(binding) {
            requireCurrent()
            val now = System.currentTimeMillis()
            val run = checkNotNull(authenticatedRun(peerId, runId, this)).first
            val marker = checkNotNull(readScopeRun(this, peerId, runId))
            check(run.transportPolicy == "connection_only" &&
                (if (reply) "request_message_id" !in marker && run.appliedRequest && run.responded
                 else connectionInitialBatchesAccepted(marker)) &&
                !run.reported && run.expiresMs > now && message.long("expires_ms") > now &&
                scopedConnectionAuthority(binding, shared, runId) == authority)
            val policy = "connection_only:$authority:$runId"
            check(!query("outbox", arrayOf("message_id"), "peer_id=? AND transport_policy=? " +
                "AND kind IN ('personal_sync.batch','personal_sync.attachment_chunk')",
                arrayOf(peerId, policy), null, null, null, "1").use { it.moveToFirst() })
            var requestedCount = 0
            for (wanted in body.getValue("wants") as JsonArray) {
                val want = wanted as JsonObject
                val hash = want.string("sha256")
                val transfer = checkNotNull(authenticatedTransfer(peerId, runId, reply, aggregate, hash, "outgoing", this))
                val expires = minOf(run.expiresMs, transfer.long("expires_ms"), message.long("expires_ms"))
                check(transfer["transport_policy"] == JsonPrimitive(policy) &&
                    transfer["complete"] == JsonPrimitive(false) && expires > now)
                for (raw in want.getValue("ranges") as JsonArray) {
                    val range = raw as JsonArray
                    val start = (range[0] as JsonPrimitive).content.toInt()
                    val end = (range[1] as JsonPrimitive).content.toInt()
                    requestedCount += end - start
                    check(start in 0 until end && end <= transfer.long("total_chunks") && requestedCount <= 8)
                    for (index in start until end) {
                        val bytes = checkNotNull(readOutgoingAttachmentChunk(peerId, runId, reply, aggregate, hash, index))
                        try {
                            val chunk = buildJsonObject {
                                put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(runId)); put("reply", JsonPrimitive(reply))
                                put("records_hash", JsonPrimitive(aggregate)); put("sha256", JsonPrimitive(hash))
                                put("index", JsonPrimitive(index)); put("data", JsonPrimitive(java.util.Base64.getEncoder().encodeToString(bytes)))
                            }
                            PersonalSyncProtokoll.validate("personal_sync.attachment_chunk", chunk)
                            writableInsert(peerId, TelefonNachrichten.message("personal_sync.attachment_chunk",
                                chunk, expires - now, now), this, policy)
                        } finally { bytes.fill(0) }
                    }
                }
            }
            check(requestedCount in 1..8)
            check(receive(peerId, message).first == "accepted")
            requireCurrent()
        }
    }

    internal fun queueConnectionAttachmentWindow(binding: SharedSettingsBinding, shared: SharedSyncStorage, request: JsonObject,
        authority: String, reply: Boolean, recordsHash: String, descriptors: List<JsonObject>, stagedExpires: Long, requireCurrent: () -> Unit) {
        val runId = request.string("run_id")
        val peerId = binding.peerActor
        val grouped = descriptors.groupBy { it.string("sha256") }
        check(grouped.size in 1..256 && grouped.values.sumOf { it.first().long("size") } <= 50L * 1024 * 1024)
        check(grouped.values.all { matches -> matches.all {
            it["size"] == matches.first()["size"] && it["mime"] == matches.first()["mime"]
        } })
        shared.withWriteTransaction(binding) {
            val now = System.currentTimeMillis()
            val (run, savedRequest) = checkNotNull(authenticatedRun(peerId, runId, this))
            val expires = minOf(stagedExpires, run.expiresMs)
            check(savedRequest == request && !run.actor && run.transportPolicy == "connection_only" &&
                (if (reply) !run.appliedReply else !run.appliedRequest && !run.responded) &&
                connectionAllowsIncomingBatch(this, peerId, runId, reply) && !run.reported && expires > now &&
                scopedConnectionAuthority(binding, shared, runId) == authority)
            requireCurrent()
            val policy = "connection_only:$authority:$runId"
            val existing = query("outbox", arrayOf("message_id"),
                "peer_id=? AND transport_policy=? AND kind='personal_sync.attachment_request'",
                arrayOf(peerId, policy), null, null, null, "1").use { it.moveToFirst() }
            if (existing) return@withWriteTransaction
            for ((hash, matches) in grouped) {
                val descriptor = matches.first()
                registerIncomingAttachmentIn(peerId, runId, reply, recordsHash, hash, descriptor.long("size").toInt(),
                    descriptor.string("mime"), policy, expires)
            }
            val window = grouped.keys.sorted().firstNotNullOfOrNull { hash ->
                val firstRange = missingAttachmentRanges(peerId, runId, reply, recordsHash, hash).firstOrNull()
                firstRange?.let { hash to it }
            } ?: return@withWriteTransaction
            val (hash, range) = window
            val boundedRange = JsonArray(listOf(JsonPrimitive(range[0]), JsonPrimitive(minOf(range[0] + 8, range[1]))))
            val body = buildJsonObject {
                put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(runId)); put("reply", JsonPrimitive(reply))
                put("records_hash", JsonPrimitive(recordsHash)); put("wants", JsonArray(listOf(buildJsonObject {
                    put("sha256", JsonPrimitive(hash))
                    put("ranges", JsonArray(listOf(boundedRange)))
                })))
            }
            PersonalSyncProtokoll.validate("personal_sync.attachment_request", body)
            writableInsert(peerId, TelefonNachrichten.message("personal_sync.attachment_request", body, expires - now, now),
                this, policy)
            requireCurrent()
        }
    }

    internal fun stageConnectionAttachmentChunk(binding: SharedSettingsBinding, shared: SharedSyncStorage,
        message: JsonObject, authority: String, requireCurrent: () -> Unit, advanceWindow: () -> Unit) {
        val body = message.getValue("body") as JsonObject
        check(message.string("kind") == "personal_sync.attachment_chunk")
        val reply = body.getValue("reply").jsonPrimitive.content.toBooleanStrict()
        val peerId = binding.peerActor
        val runId = body.string("run_id")
        val aggregate = body.string("records_hash")
        val hash = body.string("sha256")
        val index = body.long("index").toInt()
        shared.withWriteTransaction(binding) {
            requireCurrent()
            val now = System.currentTimeMillis()
            val policy = "connection_only:$authority:$runId"
            check(scopedConnectionAuthority(binding, shared, runId) == authority && message.long("expires_ms") > now)
            val windowId = query("outbox", arrayOf("message_id"),
                "peer_id=? AND transport_policy=? AND kind='personal_sync.attachment_request' AND attempts>0 " +
                    "AND expires_ms>? AND last_error IN ('','connection_window_ack')",
                arrayOf(peerId, policy, now.toString()), null, null, null).use { row ->
                    check(row.moveToFirst()) { "Attachment window has not been sent" }
                    row.getString(0).also { check(!row.moveToNext()) }
                }
            val window = checkNotNull(outboxPersonalMessage(peerId, windowId))
            check(connectionCompletionPolicy(this, peerId, window, now) == policy)
            val requested = window.getValue("body") as JsonObject
            val want = (requested.getValue("wants") as JsonArray).single() as JsonObject
            check(requested["reply"] == body["reply"] && requested.string("records_hash") == aggregate && want.string("sha256") == hash)
            val range = (want.getValue("ranges") as JsonArray).single() as JsonArray
            val start = (range[0] as JsonPrimitive).content.toInt()
            val end = (range[1] as JsonPrimitive).content.toInt()
            check(index in start until end &&
                missingAttachmentRanges(peerId, runId, reply, aggregate, hash).any { index in it[0] until it[1] })
            val transfer = checkNotNull(authenticatedTransfer(peerId, runId, reply, aggregate, hash, "incoming", this))
            val bytes = java.util.Base64.getDecoder().decode(body.string("data"))
            try {
                stageAttachmentChunkIn(this, peerId, runId, reply, aggregate, hash, transfer.long("size").toInt(),
                    transfer.string("mime"), index, bytes, "incoming", policy, transfer.long("expires_ms"))
            } finally { bytes.fill(0) }
            val missing = missingAttachmentRanges(peerId, runId, reply, aggregate, hash)
            if (missing.isEmpty()) {
                val sink = object : OutputStream() {
                    override fun write(value: Int) {}
                    override fun write(bytes: ByteArray, offset: Int, length: Int) {}
                }
                require(verifyIncomingAttachment(peerId, runId, reply, aggregate, hash, sink)) { "Invalid original attachment bytes" }
            }
            if (missing.none { it[0] < end && start < it[1] }) {
                check(delete("outbox", "peer_id=? AND message_id=?", arrayOf(peerId, windowId)) == 1)
                advanceWindow()
            }
            check(receive(peerId, message).first == "accepted")
            requireCurrent()
        }
    }

    private fun connectionCompletionPending(db: SQLiteDatabase, peerId: String, runId: String, policy: String): Boolean =
        db.query("outbox", arrayOf("message_id"), "peer_id=? AND transport_policy=? " +
            "AND kind IN ('personal_sync.batch','personal_sync.attachment_result','personal_sync.attachment_chunk')",
            arrayOf(peerId, policy), null, null, null, "1").use { it.moveToFirst() } ||
            hasAuthenticatedOutgoingAttachments(peerId, runId, pendingOnly = true, db = db)

    private fun releaseConnectionReport(db: SQLiteDatabase, peerId: String, runId: String, policy: String, now: Long) {
        if (connectionCompletionPending(db, peerId, runId, policy)) return
        db.update("outbox", ContentValues().apply {
            put("last_error", ""); put("next_attempt_ms", now)
        }, "peer_id=? AND transport_policy=? AND kind='personal_sync.report' AND last_error='connection_held'",
            arrayOf(peerId, policy))
    }

    private fun writeConnectionOutgoingTransfer(db: SQLiteDatabase, transfer: JsonObject) {
        val peerId = transfer.string("peer_id")
        val runId = transfer.string("run_id")
        val aggregate = transfer.string("records_hash")
        val hash = transfer.string("sha256")
        val reply = transfer.getValue("reply").jsonPrimitive.content.toBooleanStrict()
        val clear = TelefonKanonisch.bytes(transfer)
        val sealed = try {
            storage.encryptPayload(clear, "personal_attachment_transfer",
                metadataPrimary(peerId, runId, reply, aggregate, hash, "outgoing"))
        } finally { clear.fill(0) }
        check(db.update("personal_attachment_transfer", ContentValues().apply {
            put("metadata", sealed)
            put("complete", if (transfer["complete"] == JsonPrimitive(true)) 1 else 0)
        }, "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing'",
            arrayOf(peerId, runId, if (reply) "1" else "0", aggregate, hash)) == 1)
    }

    internal fun receiveConnectionAttachmentResult(binding: SharedSettingsBinding, shared: SharedSyncStorage,
        message: JsonObject, authority: String, requireCurrent: () -> Unit) {
        val body = message.getValue("body") as JsonObject
        check(message.string("kind") == "personal_sync.attachment_result" &&
             body["state"] == JsonPrimitive("complete") && body["error"] == JsonPrimitive("none"))
        val reply = body.getValue("reply").jsonPrimitive.content.toBooleanStrict()
        val peerId = binding.peerActor
        val runId = body.string("run_id")
        val hash = body.string("sha256")
        val aggregate = body.string("records_hash")
        shared.withWriteTransaction(binding) {
            requireCurrent()
            val now = System.currentTimeMillis()
            val run = checkNotNull(authenticatedRun(peerId, runId, this)).first
            val transfer = checkNotNull(authenticatedTransfer(peerId, runId, reply, aggregate, hash, "outgoing", this))
            val policy = "connection_only:$authority:$runId"
            val marker = checkNotNull(readScopeRun(this, peerId, runId))
            check(run.transportPolicy == "connection_only" &&
                (if (reply) "request_message_id" !in marker && run.appliedRequest && run.responded
                 else connectionInitialBatchesAccepted(marker)) &&
                !run.reported && run.expiresMs > now && message.long("expires_ms") > now &&
                scopedConnectionAuthority(binding, shared, runId) == authority &&
                transfer["transport_policy"] == JsonPrimitive(policy) && transfer["complete"] == JsonPrimitive(false) &&
                transfer.long("expires_ms") > now)
            val count = transfer.long("total_chunks").toInt()
            check(count in 1..47 && transfer["acked_chunks"] == JsonPrimitive((1L shl count) - 1))
            val pending = query("outbox", arrayOf("message_id"), "peer_id=? AND transport_policy=? AND kind='personal_sync.attachment_chunk'",
                arrayOf(peerId, policy), null, null, null).use { rows ->
                while (rows.moveToNext()) {
                    val chunk = checkNotNull(outboxPersonalMessage(peerId, rows.getString(0))).getValue("body") as JsonObject
                    if (chunk["records_hash"] == body["records_hash"] && chunk["sha256"] == body["sha256"]) return@use true
                }
                false
            }
            check(!pending)
            writeConnectionOutgoingTransfer(this, JsonObject(transfer + ("complete" to JsonPrimitive(true))))
            check(receive(peerId, message).first == "accepted")
            if (reply) releaseConnectionReport(this, peerId, runId, policy, now)
            requireCurrent()
        }
    }

    internal fun queueConnectionAttachmentResults(binding: SharedSettingsBinding, shared: SharedSyncStorage, request: JsonObject,
        authority: String, aggregate: String, hashes: Set<String>, requireSaved: () -> Unit) {
        val peerId = binding.peerActor
        val runId = request.string("run_id")
        shared.withWriteTransaction(binding) {
            val now = System.currentTimeMillis()
            val (run, savedRequest) = checkNotNull(authenticatedRun(peerId, runId, this))
            check(savedRequest == request && !run.actor && run.transportPolicy == "connection_only" &&
                !run.reported && run.expiresMs > now && scopedConnectionAuthority(binding, shared, runId) == authority)
            if (run.appliedRequest) return@withWriteTransaction
            requireSaved()
            writeConnectionIncomingResults(this, peerId, runId, false, authority, aggregate, hashes, run.expiresMs)
            updatePersonalRun(this, peerId, runId) { it.copy(appliedRequest = true) }
            requireSaved()
        }
    }

    private fun writeConnectionIncomingResults(db: SQLiteDatabase, peerId: String, runId: String, reply: Boolean,
                                               authority: String, aggregate: String, hashes: Set<String>, runExpiry: Long): List<String> {
        val now = System.currentTimeMillis()
        val policy = "connection_only:$authority:$runId"
        return hashes.sorted().map { hash ->
            val transfer = checkNotNull(authenticatedTransfer(peerId, runId, reply, aggregate, hash, "incoming", db))
            val expires = minOf(runExpiry, transfer.long("expires_ms"))
            check(transfer["complete"] == JsonPrimitive(true) && transfer["transport_policy"] == JsonPrimitive(policy) && expires > now)
            val body = buildJsonObject {
                put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(runId)); put("reply", JsonPrimitive(reply))
                put("records_hash", JsonPrimitive(aggregate)); put("sha256", JsonPrimitive(hash))
                put("state", JsonPrimitive("complete")); put("error", JsonPrimitive("none"))
            }
            val message = TelefonNachrichten.message("personal_sync.attachment_result", body, expires - now, now)
            writableInsert(peerId, message, db, policy)
            message.string("message_id")
        }
    }

    internal fun queueConnectionCompletion(binding: SharedSettingsBinding, shared: SharedSyncStorage, request: JsonObject,
        authority: String, batches: List<JsonObject>, report: JsonObject,
        originals: Map<String, PersonalSync.AttachmentSnapshot>, requireCurrent: () -> Unit) {
        val runId = request.string("run_id")
        val peerId = binding.peerActor
        check(batches.isNotEmpty())
        shared.withWriteTransaction(binding) {
            val now = System.currentTimeMillis()
            val (run, savedRequest) = checkNotNull(authenticatedRun(peerId, runId, this))
            check(savedRequest == request && !run.actor && run.transportPolicy == "connection_only" &&
                !run.reported && run.expiresMs > now && scopedConnectionAuthority(binding, shared, runId) == authority)
            if (run.responded) return@withWriteTransaction
            requireCurrent()
            val policy = "connection_only:$authority:$runId"
            PersonalSyncProtokoll.validate("personal_sync.report", report)
            check(report["trigger"] == request["trigger"] && report["run_id"] == request["run_id"] &&
                report["format"] == request["format"] && report["state"] == JsonPrimitive("complete"))
            val recordsHash = batches.first().string("records_hash")
            val records = batches.flatMapIndexed { index, body ->
                check(body["reply"] == JsonPrimitive(true) && body.long("sequence") == index.toLong() &&
                    body["last"] == JsonPrimitive(index == batches.lastIndex) && body.string("records_hash") == recordsHash)
                PersonalSyncProtokoll.validateBatchForRequest(request, body)
            }
            check(PersonalSync.recordsHash(records) == recordsHash)
            val advertised = records.filter { it.kind == "note" }.flatMap {
                (it.value["attachments"] as? JsonArray).orEmpty().map { raw -> raw as JsonObject }
            }.groupBy { it.string("sha256") }
            check(advertised.keys == originals.keys)
            for ((hash, source) in originals) {
                val bytes = source.bytes
                val mime = source.descriptor.string("mime")
                check(bytes.size in 1..AnhangPruefung.ROH_MAX && sha256(bytes) == hash && AnhangPruefung.mime(bytes) == mime &&
                    advertised.getValue(hash).all { it.long("size") == bytes.size.toLong() && it.string("mime") == mime })
                val width = PersonalSyncProtokoll.CHUNK_RAW
                for (offset in bytes.indices step width) {
                    val chunk = bytes.copyOfRange(offset, minOf(bytes.size, offset + width))
                    try {
                        stageAttachmentChunkIn(this, peerId, runId, true, recordsHash, hash, bytes.size, mime,
                            offset / width, chunk, "outgoing", policy, run.expiresMs)
                    } finally { chunk.fill(0) }
                }
            }
            for (body in batches) {
                writableInsert(peerId, TelefonNachrichten.message("personal_sync.batch", body, run.expiresMs - now, now),
                    this, policy)
            }
            val held = writableInsert(peerId, TelefonNachrichten.message("personal_sync.report", report, run.expiresMs - now, now),
                this, policy)
            check(update("outbox", ContentValues().apply {
                put("last_error", "connection_held"); put("next_attempt_ms", run.expiresMs)
            }, "peer_id=? AND message_id=?", arrayOf(peerId, held.string("message_id"))) == 1)
            updatePersonalRun(this, peerId, runId) { it.copy(appliedRequest = true, responded = true) }
            requireCurrent()
        }
    }

    internal fun acknowledgeConnectionCompletion(peerId: String, message: JsonObject, status: String, error: String): Boolean =
        helper.writableDatabase.inTransaction {
            val now = System.currentTimeMillis()
            val policy = connectionCompletionPolicy(this, peerId, message, now) ?: return@inTransaction false
            val id = message.string("message_id")
            val where = "peer_id=? AND message_id=? AND transport_policy=? AND attempts>0 AND expires_ms>? AND last_error=''"
            val args = arrayOf(peerId, id, policy, now.toString())
            if (outboxPersonalMessage(peerId, id) != message) return@inTransaction false
            if (status !in setOf("accepted", "duplicate")) {
                if (error != "temporary_failure") update("outbox", ContentValues().apply {
                    put("last_error", "connection_rejected"); put("next_attempt_ms", message.long("expires_ms"))
                }, where, args)
                return@inTransaction false
            }
            val kind = message.string("kind")
            if (kind == "personal_sync.attachment_request") {
                update("outbox", ContentValues().apply {
                    put("last_error", "connection_window_ack"); put("next_attempt_ms", message.long("expires_ms"))
                }, where, args)
                return@inTransaction false
            }
            if (delete("outbox", where, args) != 1) return@inTransaction false
            val body = message.getValue("body") as JsonObject
            val runId = body.string("run_id")
            if (kind == "personal_sync.attachment_chunk") {
                val aggregate = body.string("records_hash")
                val hash = body.string("sha256")
                val reply = body.getValue("reply").jsonPrimitive.content.toBooleanStrict()
                val transfer = checkNotNull(authenticatedTransfer(peerId, runId, reply, aggregate, hash, "outgoing", this))
                check(transfer["transport_policy"] == JsonPrimitive(policy))
                val previous = if ("acked_chunks" in transfer) transfer.long("acked_chunks") else 0L
                val mask = previous or (1L shl body.long("index").toInt())
                writeConnectionOutgoingTransfer(this, JsonObject(transfer + ("acked_chunks" to JsonPrimitive(mask))))
                return@inTransaction false
            }
            if (kind == "personal_sync.batch" || kind == "personal_sync.attachment_result") {
                if (kind == "personal_sync.attachment_result" && body["reply"] == JsonPrimitive(true)) {
                    val marker = checkNotNull(readScopeRun(this, peerId, runId))
                    val results = marker.getValue("reply_results").jsonObject
                    writeScopeMarker(this, peerId, runId, JsonObject(marker +
                        ("reply_results" to JsonObject(results + (id to JsonPrimitive(true))))))
                    return@inTransaction false
                }
                releaseConnectionReport(this, peerId, runId, policy, now)
                return@inTransaction false
            }
            updatePersonalRun(this, peerId, runId) { it.copy(reported = true) }
            finishPersonalBatch(peerId, runId, reply = false)
            true
        }

    /** One transaction owns the binding, all batches/attachments and the exact request receipt. */
    internal fun queueScopedRequest(binding: SharedSettingsBinding, shared: SharedSyncStorage,
        message: JsonObject, reference: JsonObject, batches: List<JsonObject>,
        attachments: List<Triple<String, String, ByteArray>>, now: Long = System.currentTimeMillis(), actorRun: Boolean = false,
        nativeActorProposals: List<JsonObject> = emptyList(), connectionAuthority: String? = null,
        requireCurrent: (() -> Unit)? = null): Boolean {
        TelefonNachrichten.validate(message)
        require(message.string("kind") == "personal_sync.request")
        val request = message.getValue("body") as JsonObject
        PersonalSyncProtokoll.validate("personal_sync.request", request)
        require(request.long("format") in setOf(3L, 14L) && batches.isNotEmpty())
        val runId = request.string("run_id")
        require(nativeActorProposals.isEmpty() || actorRun) { "actor_proposal_context_required" }
        require(nativeActorProposals.size <= 8 && nativeActorProposals.map { it.string("message_id") }.distinct().size == nativeActorProposals.size)
        var proposalBatch: String? = null
        val proposalIds = mutableSetOf<String>()
        nativeActorProposals.forEachIndexed { index, proposal ->
            TelefonNachrichten.validate(proposal)
            require(proposal.string("kind") == "personal_sync.deletion_proposals" &&
                proposal.long("expires_ms") <= message.long("expires_ms")) { "actor_proposal_envelope_changed" }
            val body = proposal.getValue("body").jsonObject
            val decoded = PersonalSyncProtokoll.decodeDeletionProposals(body)
            if (proposalBatch == null) proposalBatch = body.string("proposal_batch_id")
            require(body.string("run_id") == runId && body.string("proposal_batch_id") == proposalBatch &&
                body.long("sequence") == index.toLong() && body["last"] == JsonPrimitive(index == nativeActorProposals.lastIndex) &&
                decoded.isNotEmpty() && decoded.size <= 32 && decoded.all { proposalIds.add(it.proposalId) }) { "actor_proposal_batch_changed" }
        }
        val recordsHash = batches.first().string("records_hash")
        batches.forEachIndexed { index, batch ->
            PersonalSyncProtokoll.validate("personal_sync.batch", batch)
            require(batch.string("run_id") == runId && batch.long("format") == request.long("format") &&
                batch.long("sequence") == index.toLong() && batch["last"] == JsonPrimitive(index == batches.lastIndex) &&
                batch["reply"] == JsonPrimitive(false) && batch.string("records_hash") == recordsHash)
        }
        val records = batches.flatMap(PersonalSyncProtokoll::decodeBatch)
        require(io.gitlab.maik3531.magnolienotes.daten.PersonalSync.recordsHash(records) == recordsHash)
        val advertised = records.filter { it.kind == "note" }.flatMap { (it.value["attachments"] as? JsonArray).orEmpty() }
            .map { (it as JsonObject).string("sha256") }.toSet()
        require(attachments.map { it.first }.distinct().size == attachments.size && attachments.all { it.first in advertised })
        val connection = request.string("trigger") == PersonalAutoSync.CONNECTION
        require(connection == (connectionAuthority != null) && connection == (requireCurrent != null))
        return shared.withWriteTransaction(binding) {
            if (hasActiveScopedRunIn(this, binding.peerActor, now, connectionAuthority)) return@withWriteTransaction false
            requireCurrent?.invoke()
            if (connectionAuthority != null) retireDisplacedConnectionStarts(this, binding.peerActor, connectionAuthority)
            rememberScopedRun(binding, shared, request, reference, message.long("expires_ms"), now, actorRun, connectionAuthority)
            val marker = requireNotNull(readScopeRun(this, binding.peerActor, runId))
            val connectionBatches = if (connection) batches.map { batch ->
                val created = message.long("created_ms")
                TelefonNachrichten.message("personal_sync.batch", batch, message.long("expires_ms") - created, created)
            } else null
            val receipt = mapOf("request_message_id" to message.getValue("message_id"), "request_accepted" to JsonPrimitive(false))
            val planned = if (connectionBatches == null) emptyMap() else mapOf("initial_batches" to JsonObject(
                connectionBatches.associate { it.string("message_id") to JsonPrimitive(false) }))
            writeScopeMarker(this, binding.peerActor, runId, JsonObject(marker + receipt + planned))
            val policy = if (connection) connectionPolicy(marker, runId) else PersonalAutoSync.policy(request.string("trigger"))
            queueFormat2DirectionIn(this, binding.peerActor, runId, false, recordsHash, null, batches,
                attachments, policy, message.long("expires_ms"), connectionBatches)
            writableInsert(binding.peerActor, message, this, policy)
            for (proposal in nativeActorProposals) {
                // Outbox and exact native target evidence share this SQLite
                // transaction. A failed later insert exposes neither half.
                writableInsert(binding.peerActor, proposal, this, policy, actorRunId = runId)
                stageActorDeletionIntent(runId, proposal, outgoing = true)
            }
            requireCurrent?.invoke()
            true
        }
    }

    private fun writeScopeMarker(db: SQLiteDatabase, peerId: String, runId: String, marker: JsonObject) {
        val key = "personal_scope:$peerId:$runId"
        val clear = TelefonKanonisch.bytes(marker)
        val sealed = try { storage.encryptPayload(clear, "personal_scope", key) } finally { clear.fill(0) }
        check(db.update("meta", ContentValues().apply { put("value", sealed) }, "key=?", arrayOf(key)) == 1)
    }

    internal fun scopedRequestAccepted(peerId: String, runId: String): Boolean {
        val marker = readScopeRun(helper.readableDatabase, peerId, runId) ?: return false
        return !marker.containsKey("request_message_id") || marker["request_accepted"] == JsonPrimitive(true)
    }

    internal fun acknowledgeScopedRequest(peerId: String, messageId: String, status: String, error: String): Boolean =
        helper.writableDatabase.inTransaction {
            val message = outboxPersonalMessage(peerId, messageId)?.let(PersonalSyncActor::semanticMessage) ?: return@inTransaction false
            if (message.string("kind") != "personal_sync.request") return@inTransaction false
            val runId = (message.getValue("body") as JsonObject).string("run_id")
            val marker = readScopeRun(this, peerId, runId) ?: return@inTransaction false
            if (marker["request_message_id"] != JsonPrimitive(messageId)) return@inTransaction false
            if ("connection_authority" in marker) return@inTransaction false
            if (status == "rejected" && error == "temporary_failure") return@inTransaction true
            if (status in setOf("accepted", "duplicate")) {
                writeScopeMarker(this, peerId, runId, JsonObject(marker + ("request_accepted" to JsonPrimitive(true))))
                delete("outbox", "peer_id=? AND message_id=?", arrayOf(peerId, messageId))
            } else {
                retireScopedRequests(this, peerId, setOf(runId))
            }
            true
        }

    private fun retireScopedRequests(db: SQLiteDatabase, peerId: String, runIds: Set<String>) = with(db) {
        purgeWireRuns(this, peerId, runIds)
        for (runId in runIds) {
            for (table in listOf("personal_run", "personal_batch", "personal_attachment_chunk", "personal_attachment_transfer"))
                delete(table, "peer_id=? AND run_id=?", arrayOf(peerId, runId))
            delete("meta", "key IN (?,?)", arrayOf("personal_scope:$peerId:$runId", "personal_report:$peerId:$runId"))
        }
    }

    private fun retireDisplacedConnectionStarts(db: SQLiteDatabase, peerId: String, authority: String) {
        val retire = mutableListOf<String>()
        db.query("personal_run", arrayOf("run_id"), "peer_id=?", arrayOf(peerId), null, null, null).use { rows ->
            while (rows.moveToNext()) {
                val runId = rows.getString(0)
                val marker = readScopeRun(db, peerId, runId) ?: continue
                if ("request_message_id" !in marker || "connection_authority" !in marker ||
                    marker["connection_authority"] == JsonPrimitive(authority)) continue
                val run = authenticatedRun(peerId, runId, db)?.first ?: continue
                if (!run.reported) retire += runId
            }
        }
        retireScopedRequests(db, peerId, retire.toSet())
    }

    /** Called under the owner's peer lock when membership or content preference changes. */
    internal fun purgeStaleScopedRuns(binding: SharedSettingsBinding, shared: SharedSyncStorage, reference: JsonObject?,
        nativeTerminalRuns: Set<String> = emptySet()): Set<String> {
        reference?.let(PhoneContentScope::validateReference); shared.requireWritable(binding)
        val settings = requireNotNull(shared.read(binding))
        val policy = if (SharedSyncSettings.effective(settings)["content_mode"] == JsonPrimitive("phone_scope")) contentPolicyHash(settings) else null
        val stale = mutableSetOf<String>()
        helper.readableDatabase.query("meta", arrayOf("key"), "key LIKE ?", arrayOf("personal_scope:${binding.peerActor}:%"), null, null, null).use { cursor ->
            while (cursor.moveToNext()) {
                val runId = cursor.getString(0).substringAfterLast(':')
                val marker = requireNotNull(readScopeRun(helper.readableDatabase, binding.peerActor, runId))
                // Retention of native terminal metadata is not data admission.
                // The controller has retired its data owner and must still check
                // exact saved book/expected membership/authority before any send.
                val finishingDeletion = reference != null && policy != null &&
                    (runId in nativeTerminalRuns || hasDeletionReceipt(binding.peerActor, runId))
                if (reference == null || policy == null || marker["scope"] != reference && !finishingDeletion || marker["peer_key"] != JsonPrimitive(binding.peerPublic) ||
                    marker["local_actor"] != JsonPrimitive(binding.localActor) || marker["content_policy"] != JsonPrimitive(policy) ||
                    marker["restore_epoch"] != JsonPrimitive(restoreEpoch())) stale.add(runId)
            }
        }
        if (stale.isEmpty()) return stale
        helper.writableDatabase.inTransaction {
            retireScopedRequests(this, binding.peerActor, stale)
        }
        return stale
    }

    private fun hasDeletionReceipt(peerId: String, runId: String): Boolean = helper.readableDatabase.query("outbox",
        arrayOf("message_id", "payload"), "peer_id=? AND kind=?", arrayOf(peerId, "personal_sync.deletion_decision"), null, null, null).use { cursor ->
        var found = false
        while (cursor.moveToNext()) {
            val clear = storage.decryptPayload(cursor.getBlob(1), "outbox", cursor.getString(0))
            try {
                val wire = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                if (PersonalSyncActor.isReservedMessage(wire)) continue // Never use the legacy data-owner exception for actor frames.
                val body = wire["body"] as JsonObject
                if (body["run_id"] == JsonPrimitive(runId) && (body["decisions"] as JsonArray).all {
                    (it as JsonObject)["decision"] == JsonPrimitive("delete") }) found = true
            } finally { clear.fill(0) }
        }
        found
    }

    private fun authenticatedRun(peerId: String, runId: String,
                                 db: SQLiteDatabase = helper.readableDatabase): Pair<PersonalRunIndex, JsonObject>? {
        val key = "personal_run:$peerId:$runId"
        return db.query("personal_run", arrayOf("peer_id", "run_id", "trigger", "transport_policy", "created_ms",
            "expires_ms", "applied_request", "applied_reply", "responded", "reported", "payload"),
            "peer_id=? AND run_id=?", arrayOf(peerId, runId), null, null, null).use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val index = PersonalRunIndex(cursor.getString(0), cursor.getString(1), cursor.getString(2), cursor.getString(3),
                cursor.getLong(4), cursor.getLong(5), cursor.getInt(6) == 1, cursor.getInt(7) == 1,
                cursor.getInt(8) == 1, cursor.getInt(9) == 1)
            val clear = storage.decryptPayload(cursor.getBlob(10), "personal_run", key)
            try {
                val envelope = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                val epoch = (envelope["restore_epoch"] as? JsonPrimitive)?.content.orEmpty()
                if (epoch != restoreEpoch()) return@use null
                val actorField = envelope["actor"]
                require(actorField == null || actorField == JsonPrimitive(true)) { "Invalid protected actor classification" }
                val stopped = envelope["actor_stopped"]
                require(stopped == null || stopped == JsonPrimitive(true) && actorField == JsonPrimitive(true)) { "Invalid protected actor stop marker" }
                val protectedIndex = index.copy(actor = actorField == JsonPrimitive(true), actorStopped = stopped == JsonPrimitive(true))
                protectedIndex to PersonalRunAuthentication.authenticate(JsonObject(envelope - "restore_epoch"), protectedIndex)
            } finally { clear.fill(0) }
        }
    }

    private fun currentRun(peerId: String, runId: String): Pair<PersonalRunIndex, JsonObject>? =
        authenticatedRun(peerId, runId)?.also {
            PersonalRunAuthentication.requireCurrent(it.first, System.currentTimeMillis())
        }

    fun personalRun(peerId: String, runId: String): JsonObject? = currentRun(peerId, runId)?.second

    fun personalRunPolicy(peerId: String, runId: String): String? = currentRun(peerId, runId)?.first?.transportPolicy

    private fun sealedActorRun(peerId: String, runId: String, db: SQLiteDatabase = helper.readableDatabase): Boolean =
        db.query("personal_run", arrayOf("payload"), "peer_id=? AND run_id=?", arrayOf(peerId, runId), null, null, null).use { row ->
            if (!row.moveToFirst()) return@use false
            val clear = storage.decryptPayload(row.getBlob(0), "personal_run", "personal_run:$peerId:$runId")
            try {
                val envelope = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                val flag = envelope["actor"]
                require(flag == null || flag == JsonPrimitive(true)) { "Invalid protected actor classification" }
                flag == JsonPrimitive(true)
            } finally { clear.fill(0) }
        }

    internal fun isActorRun(peerId: String, runId: String): Boolean = sealedActorRun(peerId, runId)

    fun personalDirectionApplied(peerId: String, runId: String, reply: Boolean): Boolean =
        currentRun(peerId, runId)?.first?.let { if (reply) it.appliedReply else it.appliedRequest } == true

    private fun updatePersonalRun(db: SQLiteDatabase, peerId: String, runId: String,
                                  allowExpired: Boolean = false,
                                  transform: (PersonalRunIndex) -> PersonalRunIndex) {
        val (old, request) = authenticatedRun(peerId, runId, db)
            ?: throw TelefonProtokollFehler("Personal-Sync-Lauf fehlt.")
        if (!allowExpired && old.expiresMs <= System.currentTimeMillis())
            throw TelefonProtokollFehler("Personal-Sync-Lauf ist abgelaufen.")
        val next = transform(old)
        require(next.actor == old.actor) { "Cannot change protected actor classification" }
        require(!old.actorStopped || next.actorStopped) { "Cannot reactivate a stopped actor" }
        val encrypted = storage.encryptPayload(TelefonKanonisch.bytes(runEnvelope(next, request)),
            "personal_run", "personal_run:$peerId:$runId")
        val values = ContentValues().apply {
            put("trigger", next.trigger); put("transport_policy", next.transportPolicy); put("created_ms", next.createdMs)
            put("expires_ms", next.expiresMs); put("applied_request", if (next.appliedRequest) 1 else 0)
            put("applied_reply", if (next.appliedReply) 1 else 0); put("responded", if (next.responded) 1 else 0)
            put("reported", if (next.reported) 1 else 0); put("payload", encrypted)
        }
        if (db.update("personal_run", values, "peer_id=? AND run_id=?", arrayOf(peerId, runId)) != 1)
            throw TelefonProtokollFehler("Personal-Sync-Lauf fehlt.")
    }

    private fun runEnvelope(index: PersonalRunIndex, request: JsonObject) = JsonObject(
        PersonalRunAuthentication.envelope(index, request) + ("restore_epoch" to JsonPrimitive(restoreEpoch())))

    fun markPersonalDirectionApplied(peerId: String, runId: String, reply: Boolean) {
        helper.writableDatabase.inTransaction { updatePersonalRun(this, peerId, runId) {
            if (reply) it.copy(appliedReply = true) else it.copy(appliedRequest = true)
        } }
    }

    fun personalRunMarked(peerId: String, runId: String, field: String): Boolean {
        require(field in setOf("responded", "reported"))
        return currentRun(peerId, runId)?.first?.let { if (field == "responded") it.responded else it.reported } == true
    }

    fun markPersonalRun(peerId: String, runId: String, field: String) {
        require(field in setOf("responded", "reported"))
        helper.writableDatabase.inTransaction { updatePersonalRun(this, peerId, runId) {
            if (field == "responded") it.copy(responded = true) else it.copy(reported = true)
        } }
    }

    internal fun stopActorRun(peerId: String, runId: String) {
        helper.writableDatabase.inTransaction {
            updatePersonalRun(this, peerId, runId, allowExpired = true) {
                require(it.actor) { "Not an actor run" }
                it.copy(actorStopped = true, reported = true)
            }
            // Retain sealed evidence, but do not let stopped rows occupy the due query's limit.
            val ids = mutableListOf<String>()
            query("outbox", arrayOf("message_id", "payload"), "peer_id=?", arrayOf(peerId), null, null, null).use { rows ->
                while (rows.moveToNext()) {
                    val id = rows.getString(0)
                    val clear = storage.decryptPayload(rows.getBlob(1), "outbox", id)
                    try {
                        val wire = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                        val body = wire["body"] as? JsonObject
                        if (wire["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) && body?.get("run_id") == JsonPrimitive(runId)) ids += id
                    } finally { clear.fill(0) }
                }
            }
            ids.forEach { id -> update("outbox", ContentValues().apply { put("next_attempt_ms", Long.MAX_VALUE) },
                "peer_id=? AND message_id=?", arrayOf(peerId, id)) }
        }
    }

    internal fun stopCurrentActorRun(peerId: String, runId: String) {
        helper.writableDatabase.inTransaction {
            // A restored/removed run cannot be reauthenticated or rebound to the new book.
            if (authenticatedRun(peerId, runId, this)?.first?.actor == true) stopActorRun(peerId, runId)
        }
    }

    fun queuePersonalCompletion(peerId: String, runId: String, batches: List<JsonObject>, report: JsonObject,
                                transportPolicy: String, recordsHash: String = "",
                                attachments: List<Triple<String, String, ByteArray>> = emptyList()): Boolean {
        require(transportPolicy in setOf("any", "wifi_only"))
        return helper.writableDatabase.inTransaction {
            val authenticated = authenticatedRun(peerId, runId, this)?.first
                ?: throw TelefonProtokollFehler("Personal-Sync-Lauf fehlt.")
            if (authenticated.expiresMs <= System.currentTimeMillis())
                throw TelefonProtokollFehler("Personal-Sync-Lauf ist abgelaufen.")
            if (authenticated.transportPolicy != transportPolicy)
                throw TelefonProtokollFehler("Widersprüchliche Personal-Sync-Policy.")
            if (authenticated.responded || authenticated.reported) return@inTransaction false
            attachments.forEach { (hash, mime, bytes) ->
                require(recordsHash.isNotEmpty() && bytes.isNotEmpty() && bytes.size <= AnhangPruefung.ROH_MAX &&
                    AnhangPruefung.mime(bytes) == mime && sha256(bytes) == hash)
                var offset = 0
                while (offset < bytes.size) {
                    val index = offset / PersonalSyncProtokoll.CHUNK_RAW
                    val chunk = bytes.copyOfRange(offset, minOf(bytes.size, offset + PersonalSyncProtokoll.CHUNK_RAW))
                    stageAttachmentChunkIn(this, peerId, runId, true, recordsHash, hash, bytes.size, mime,
                        index, chunk, "outgoing", transportPolicy, System.currentTimeMillis() + 86_400_000)
                    chunk.fill(0); offset += PersonalSyncProtokoll.CHUNK_RAW
                }
            }
            batches.forEach { body -> writableInsert(peerId, TelefonNachrichten.message("personal_sync.batch", body, 86_400_000), this, transportPolicy) }
            val format2Pending = report.long("format") >= 2L && hasAuthenticatedOutgoingAttachments(peerId, runId)
            if (format2Pending) {
                val key = "personal_report:$peerId:$runId"
                val encrypted = storage.encryptPayload(TelefonKanonisch.bytes(report), "personal_report", key)
                phoneCapacity("meta", encrypted.size, 1024)
                insertWithOnConflict("meta", null, ContentValues().apply { put("key", key); put("value", encrypted) },
                    SQLiteDatabase.CONFLICT_REPLACE)
            } else writableInsert(peerId, TelefonNachrichten.message("personal_sync.report", report, 86_400_000), this, transportPolicy)
            updatePersonalRun(this, peerId, runId) { it.copy(responded = true, reported = !format2Pending) }
            true
        }
    }

    fun releasePersonalReport(peerId: String, runId: String, transportPolicy: String) {
        if (currentRun(peerId, runId)?.first?.transportPolicy != transportPolicy)
            throw TelefonProtokollFehler("Widersprüchliche Personal-Sync-Policy.")
        val pending = hasAuthenticatedOutgoingAttachments(peerId, runId)
        if (pending) return
        val key = "personal_report:$peerId:$runId"
        val encrypted = helper.readableDatabase.query("meta", arrayOf("value"), "key=?", arrayOf(key), null, null, null).use {
            if (it.moveToFirst()) it.getBlob(0) else null } ?: return
        val clear = storage.decryptPayload(encrypted, "personal_report", key)
        try {
            val report = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
            helper.writableDatabase.inTransaction {
                writableInsert(peerId, TelefonNachrichten.message("personal_sync.report", report, 86_400_000), this, transportPolicy)
                delete("meta", "key=?", arrayOf(key))
                updatePersonalRun(this, peerId, runId) { it.copy(reported = true) }
            }
        } finally { clear.fill(0) }
    }

    fun hasActiveAutoRun(peerId: String, now: Long = System.currentTimeMillis()): Boolean = helper.readableDatabase.query(
        "personal_run", arrayOf("run_id"), "peer_id=?", arrayOf(peerId), null, null, null).use { cursor ->
        var active = false
        while (cursor.moveToNext()) {
            val index = authenticatedRun(peerId, cursor.getString(0))?.first ?: continue
            if (index.trigger == "auto_wifi" && !index.reported && index.expiresMs > now) active = true
        }
        active
    }

    fun cleanup(now: Long = System.currentTimeMillis(), protectedRuns: Set<Pair<String, String>> = emptySet()) {
        helper.writableDatabase.inTransaction {
            val partial = mutableSetOf<Pair<String, String>>()
            query(true, "personal_batch", arrayOf("peer_id", "run_id"), "expires_ms<=?", arrayOf(now.toString()),
                null, null, null, null).use { cursor -> while (cursor.moveToNext()) partial += cursor.getString(0) to cursor.getString(1) }
            delete("outbox", "expires_ms<=?", arrayOf(now.toString()))
            // An accepted control may still need its peer-file effect replayed after a crash.
            delete("inbox", "expires_ms<=? AND NOT (state='accepted' AND kind IN ('capabilities.update','grants.update'))",
                arrayOf(now.toString()))
            delete("dedupe", "seen_ms<? AND NOT EXISTS (SELECT 1 FROM inbox i WHERE i.peer_id=dedupe.peer_id AND " +
                "i.message_id=dedupe.message_id AND i.state='accepted' AND i.kind IN ('capabilities.update','grants.update'))",
                arrayOf((now - RETENTION_MS).toString()))
            delete("event_dedupe", "seen_ms<?", arrayOf((now - RETENTION_MS).toString()))
            delete("personal_batch", "expires_ms<=? OR received_ms<?", arrayOf(now.toString(), (now - 86_400_000L).toString()))
            execSQL("DELETE FROM personal_attachment_chunk WHERE EXISTS (SELECT 1 FROM personal_attachment_transfer t WHERE t.peer_id=personal_attachment_chunk.peer_id AND t.run_id=personal_attachment_chunk.run_id AND t.reply=personal_attachment_chunk.reply AND t.records_hash=personal_attachment_chunk.records_hash AND t.sha256=personal_attachment_chunk.sha256 AND t.direction=personal_attachment_chunk.direction AND t.expires_ms<=?)", arrayOf(now))
            delete("personal_attachment_transfer", "expires_ms<=?", arrayOf(now.toString()))
            query("personal_run", arrayOf("peer_id", "run_id"), null, null, null, null, null).use { cursor ->
                while (cursor.moveToNext()) {
                    val peerId = cursor.getString(0); val runId = cursor.getString(1)
                    val index = authenticatedRun(peerId, runId, this)?.first ?: continue
                    if (!index.reported && index.expiresMs <= now) partial += peerId to runId
                }
            }
            partial.forEach { (peerId, runId) ->
                val authenticated = authenticatedRun(peerId, runId, this)?.first ?: return@forEach
                val trigger = authenticated.trigger
                if (trigger == PersonalAutoSync.CONNECTION) return@forEach
                val zero = buildJsonObject { put("notes", JsonPrimitive(0)); put("tasks", JsonPrimitive(0)); put("notebooks", JsonPrimitive(0)) }
                val report = buildJsonObject {
                put("format", JsonPrimitive(1)); put("run_id", JsonPrimitive(runId)); put("state", JsonPrimitive("partial"))
                put("trigger", JsonPrimitive(trigger)); put("transport", JsonPrimitive("wifi")); put("sent", zero); put("received", zero)
                put("conflicts", JsonPrimitive(0)); put("attachments_omitted", JsonPrimitive(0)); put("oversized_skipped", JsonPrimitive(0))
                put("deletions", buildJsonObject {
                    for (name in listOf("pending", "deleted", "restored", "conflicts", "blocked")) put(name, JsonPrimitive(0))
                    put("trash", buildJsonObject { for (name in listOf("notes", "tasks", "notebooks", "attachments")) put(name, JsonPrimitive(0)) })
                })
                    put("started_ms", JsonPrimitive(now)); put("finished_ms", JsonPrimitive(now)); put("error", JsonPrimitive("protocol"))
                }
                if (authenticated.expiresMs > now) {
                    writableInsert(peerId, TelefonNachrichten.message("personal_sync.report", report, 86_400_000L, now),
                        this, authenticated.transportPolicy)
                }
                updatePersonalRun(this, peerId, runId, allowExpired = true) { it.copy(reported = true) }
            }
            val expired = mutableListOf<Pair<String, String>>()
            query("personal_run", arrayOf("peer_id", "run_id"), "expires_ms<=?", arrayOf(now.toString()),
                null, null, null).use { cursor -> while (cursor.moveToNext()) {
                val key = cursor.getString(0) to cursor.getString(1)
                if (key !in protectedRuns) expired += key
            } }
            expired.groupBy({ it.first }, { it.second }).forEach { (peerId, runs) ->
                purgeWireRuns(this, peerId, runs.toSet())
                runs.forEach { runId ->
                    for (table in listOf("personal_run", "personal_batch", "personal_attachment_transfer", "personal_attachment_chunk"))
                        delete(table, "peer_id=? AND run_id=?", arrayOf(peerId, runId))
                    delete("meta", "key=?", arrayOf("personal_report:$peerId:$runId"))
                    delete("meta", "key=?", arrayOf("personal_scope:$peerId:$runId"))
                }
            }
        }
    }

    companion object { const val RETENTION_MS = 2_592_000_000L }
}

class TelefonEffekte(context: Context) {
    private val helper = TelefonDatenbank(context.applicationContext)

    fun firstEvent(key: String, now: Long = System.currentTimeMillis()): Boolean {
        val values = ContentValues().apply { put("event_key", key); put("seen_ms", now) }
        return helper.use { it.writableDatabase.inTransaction {
            if (query("event_dedupe", arrayOf("event_key"), "event_key=?", arrayOf(key), null, null, null)
                    .use { cursor -> cursor.moveToFirst() }) return@inTransaction false
            phoneCapacity("event_dedupe", key.toByteArray(Charsets.UTF_8).size, rows = 100_000)
            insertOrThrow("event_dedupe", null, values) != -1L
        } }
    }
}
