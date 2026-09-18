package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.content.ContentValues
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import io.gitlab.maik3531.magnolienotes.daten.AnhangPruefung
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
        delete("meta", "key LIKE ?", arrayOf("%:$peerId:%"))
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
    val appliedReply: Boolean = false, val responded: Boolean = false, val reported: Boolean = false
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
    }

    fun authenticate(envelope: JsonObject, index: PersonalRunIndex): JsonObject {
        val request = envelope["request"] as? JsonObject
            ?: throw TelefonProtokollFehler("Nicht authentifizierte Personal-Sync-Metadaten.")
        val modules = request["modules"] as? JsonArray
        val expectedPolicy = if (index.trigger == "auto_wifi") "wifi_only" else "any"
        if (request["run_id"] != JsonPrimitive(index.runId) || request["trigger"] != JsonPrimitive(index.trigger) ||
            modules == null || modules.any { it !is JsonPrimitive } || modules.map { (it as JsonPrimitive).content } !in
                listOf(listOf("notes"), listOf("tasks"), listOf("notes", "tasks")) ||
            index.trigger !in setOf("manual", "auto_wifi") || index.transportPolicy != expectedPolicy ||
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

    fun queue(peerId: String, kind: String, body: JsonObject, ttlMs: Long, now: Long = System.currentTimeMillis(),
              transportPolicy: String = "any"): JsonObject {
        require(transportPolicy in setOf("any", "wifi_only"))
        val message = TelefonNachrichten.message(kind, body, ttlMs, now)
        writableInsert(peerId, message, transportPolicy = transportPolicy)
        return message
    }

    fun queuePrepared(peerId: String, message: JsonObject, transportPolicy: String = "any") {
        require(transportPolicy in setOf("any", "wifi_only"))
        writableInsert(peerId, message, transportPolicy = transportPolicy)
    }

    private fun writableInsert(peerId: String, message: JsonObject, db: SQLiteDatabase = helper.writableDatabase,
                                transportPolicy: String = "any") {
        val statusBody = message["body"] as? JsonObject
        require(!message.string("kind").startsWith("device_status.") ||
            statusBody?.containsKey("identifiers") != true && statusBody?.get("version") != JsonPrimitive(4))
        db.inTransaction {
        val id = message.string("message_id")
        val payload = storage.encryptPayload(TelefonKanonisch.bytes(message), "outbox", id)
        db.phoneCapacity("outbox", payload.size)
        val values = ContentValues().apply {
            put("message_id", id); put("peer_id", peerId); put("kind", message.string("kind"))
            put("created_ms", message.long("created_ms")); put("expires_ms", message.long("expires_ms"))
            put("payload", payload)
            put("attempts", 0); put("next_attempt_ms", message.long("created_ms")); put("last_error", "")
            put("transport_policy", transportPolicy)
        }
        db.insertOrThrow("outbox", null, values)
        }
    }

    internal fun due(peerId: String, transport: TelefonTransportArt, now: Long = System.currentTimeMillis()): List<TelefonOutboxEintrag> {
        val result = mutableListOf<TelefonOutboxEintrag>()
        helper.writableDatabase.inTransaction {
            val stale = mutableListOf<String>()
            query("outbox", arrayOf("message_id", "peer_id", "kind", "created_ms", "expires_ms",
                "transport_policy", "payload"), "peer_id=? AND next_attempt_ms<=?" +
                    if (transport == TelefonTransportArt.BLUETOOTH) " AND transport_policy='any'" else "",
                arrayOf(peerId, now.toString()), null, null,
                "CASE WHEN kind='personal_sync.custom_settings' THEN 0 ELSE 1 END,created_ms,message_id", "32").use { cursor ->
                while (cursor.moveToNext()) {
                    val id = cursor.getString(0)
                    var clear: ByteArray? = null
                    try {
                        clear = storage.decryptPayload(cursor.getBlob(6), "outbox", id)
                        val message = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                        val kind = cursor.getString(2)
                        if (cursor.getString(1) != peerId || message.string("message_id") != id ||
                            message.string("kind") != kind || message.long("created_ms") != cursor.getLong(3) ||
                            message.long("expires_ms") != cursor.getLong(4) || cursor.getLong(4) <= now) {
                            stale += id; continue
                        }
                        val stored = cursor.getString(5)
                        val effective = if (kind in PERSONAL_SYNC_DATA_KINDS) {
                            val body = message["body"] as JsonObject
                            val run = authenticatedRun(peerId, body.string("run_id"), this)?.first
                            if (run == null || run.expiresMs <= now) { stale += id; continue }
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
                try { (((TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject)["body"]
                    as JsonObject)["decision_id"] as JsonPrimitive).content } finally { clear.fill(0) }
            } }
        if (decisionId == null) {
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
            if (cursor.getString(3) != peerId || message.string("message_id") != messageId ||
                message.string("kind") != kind || message.long("created_ms") != cursor.getLong(4) ||
                message.long("expires_ms") != cursor.getLong(5)) return@use "invalid"
            val body = message["body"] as JsonObject
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
            }
        }
        // Encrypted wire rows cannot be classified in SQL; remove only rows whose decrypted run is revoked.
        purgeWireRuns(peerId, runIds.toSet())
    }

    private fun purgeWireRuns(peerId: String, runIds: Set<String>) {
        if (runIds.isEmpty()) return
        helper.writableDatabase.inTransaction {
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
                    if ((existing["body"] as JsonObject).string("decision_id") == decisionId) return existing
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
        hash: String, direction: String): JsonObject? = helper.readableDatabase.query("personal_attachment_transfer",
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
            if (actual != expected) throw TelefonProtokollFehler("Manipulierte Attachment-Metadaten.")
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

    fun queueFormat2Direction(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                              request: JsonObject?, batches: List<JsonObject>,
                              attachments: List<Triple<String, String, ByteArray>>, transportPolicy: String,
                              expiresMs: Long) {
        require(transportPolicy in setOf("any", "wifi_only"))
        helper.writableDatabase.inTransaction {
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
            batches.forEach { writableInsert(peerId, TelefonNachrichten.message("personal_sync.batch", it, 86_400_000), this, transportPolicy) }
        }
    }

    fun registerIncomingAttachment(peerId: String, runId: String, reply: Boolean, recordsHash: String,
                                   hash: String, size: Int, mime: String, transportPolicy: String,
                                   expiresMs: Long) {
        require(size in 1..AnhangPruefung.ROH_MAX && transportPolicy in setOf("any", "wifi_only"))
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
                                     transportPolicy: String, expiresMs: Long) = stageAttachmentChunk(peerId, runId,
        reply, recordsHash, hash, size, mime, index, bytes, "incoming", transportPolicy, expiresMs)

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
        require(size in 1..AnhangPruefung.ROH_MAX && index in 0 until count && policy in setOf("any", "wifi_only") &&
            bytes.size == if (index + 1 < count) PersonalSyncProtokoll.CHUNK_RAW else size - index * PersonalSyncProtokoll.CHUNK_RAW)
        val primary = attachmentPrimary(peerId, runId, reply, recordsHash, hash, index, direction)
        val encrypted = storage.encryptPayload(bytes, "personal_attachment_chunk", primary)
        run {
            fun scalar(sql: String, args: Array<String> = emptyArray()): Long = rawQuery(sql, args).use { it.moveToFirst(); it.getLong(0) }
            val transferExists = scalar("SELECT COUNT(*) FROM personal_attachment_transfer WHERE peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction=?",
                arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash, direction)) > 0
            if (!transferExists) phoneCapacity("personal_attachment_transfer", rows = 4096)
            if (transferExists) {
                val authenticated = authenticatedTransfer(peerId, runId, reply, recordsHash, hash, direction)
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
            if (policy == null || policy == "wifi_only" && transport != TelefonTransportArt.WIFI) return@forEach
            ranges.forEach { range -> (range[0] until range[1]).forEach { index ->
                val encrypted = helper.readableDatabase.query("personal_attachment_chunk", arrayOf("payload"),
                    "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing' AND chunk_index=?",
                    arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash, index.toString()), null, null, null).use {
                    if (it.moveToFirst()) it.getBlob(0) else null }
                if (encrypted != null) result += Triple(hash, index, storage.decryptPayload(encrypted,
                    "personal_attachment_chunk", attachmentPrimary(peerId, runId, reply, recordsHash, hash, index, "outgoing")))
                if (result.size == 8) return result
            } }
        }
        return result
    }

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
        authenticatedTransfer(peerId, runId, reply, recordsHash, hash, "outgoing")
            ?: throw TelefonProtokollFehler("Nicht authentifizierte Attachment-Metadaten.")
        helper.writableDatabase.inTransaction {
            delete("personal_attachment_chunk", "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing'",
                arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash))
            delete("personal_attachment_transfer", "peer_id=? AND run_id=? AND reply=? AND records_hash=? AND sha256=? AND direction='outgoing'",
                arrayOf(peerId, runId, if (reply) "1" else "0", recordsHash, hash))
        }
    }

    private fun hasAuthenticatedOutgoingAttachments(peerId: String, runId: String): Boolean {
        var found = false
        helper.readableDatabase.query("personal_attachment_transfer",
            arrayOf("reply", "records_hash", "sha256", "direction"), "peer_id=? AND run_id=?",
            arrayOf(peerId, runId), null, null, null).use { cursor -> while (cursor.moveToNext()) {
            val reply = cursor.getInt(0) == 1; val recordsHash = cursor.getString(1)
            val hash = cursor.getString(2); val direction = cursor.getString(3)
            authenticatedTransfer(peerId, runId, reply, recordsHash, hash, direction)
                ?: throw TelefonProtokollFehler("Nicht authentifizierte Attachment-Metadaten.")
            if (direction == "outgoing") found = true
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

    fun readyPersonalBatches(): List<Pair<String, List<JsonObject>>> {
        val groups = mutableListOf<Triple<String, String, Int>>()
        helper.readableDatabase.query(true, "personal_batch", arrayOf("peer_id", "run_id", "reply"), null, null,
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
                            now: Long = System.currentTimeMillis()) {
        val runId = body.string("run_id"); val key = "personal_run:$peerId:$runId"
        val trigger = body.string("trigger"); if (trigger !in setOf("manual", "auto_wifi")) throw TelefonProtokollFehler("Ungültiger Personal-Sync-Trigger.")
        helper.writableDatabase.inTransaction {
            val existing = authenticatedRun(peerId, runId, this)
            if (existing != null) {
                if (existing.second != body) throw TelefonProtokollFehler("Widersprüchlicher Personal-Sync-Lauf.")
                val expires = PersonalRunAuthentication.effectiveExpiry(wireExpiresMs, now, existing.first.expiresMs)
                if (expires != existing.first.expiresMs) updatePersonalRun(this, peerId, runId, allowExpired = true) {
                    it.copy(expiresMs = expires)
                }
                return@inTransaction
            }
            val index = PersonalRunIndex(peerId, runId, trigger, if (trigger == "auto_wifi") "wifi_only" else "any",
                now, PersonalRunAuthentication.effectiveExpiry(wireExpiresMs, now))
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
                index to PersonalRunAuthentication.authenticate(JsonObject(envelope - "restore_epoch"), index)
            } finally { clear.fill(0) }
        }
    }

    private fun currentRun(peerId: String, runId: String): Pair<PersonalRunIndex, JsonObject>? =
        authenticatedRun(peerId, runId)?.also {
            PersonalRunAuthentication.requireCurrent(it.first, System.currentTimeMillis())
        }

    fun personalRun(peerId: String, runId: String): JsonObject? = currentRun(peerId, runId)?.second

    fun personalRunPolicy(peerId: String, runId: String): String? = currentRun(peerId, runId)?.first
        ?.transportPolicy?.takeIf { it in setOf("any", "wifi_only") }

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
                purgeWireRuns(peerId, runs.toSet())
                runs.forEach { runId ->
                    for (table in listOf("personal_run", "personal_batch", "personal_attachment_transfer", "personal_attachment_chunk"))
                        delete(table, "peer_id=? AND run_id=?", arrayOf(peerId, runId))
                    delete("meta", "key=?", arrayOf("personal_report:$peerId:$runId"))
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
