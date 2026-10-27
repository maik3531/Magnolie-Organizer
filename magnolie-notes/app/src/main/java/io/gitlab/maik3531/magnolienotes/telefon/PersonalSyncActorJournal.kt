package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.UUID

/** Opaque native ownership; tokens must never enter status, wire frames or logs. */
internal class PersonalActorHandle internal constructor(val peerId: String, val runId: String, internal val token: String)

/** Protected server-journal primitive. No transport admission, receipt or document mutation.
 * currentSource must derive its revision from the actual current channel/key, book/profile,
 * fresh controls, both ownership/grant decisions and content scope. Wire revisions are not authority.
 */
internal class PersonalSyncActorJournal(
    private val database: TelefonDatenbank,
    private val storage: TelefonPayloadStorage,
    private val currentSource: (String, String) -> String?,
    private val restoreEpoch: () -> String,
    private val ownerEpoch: String = randomToken(),
    private val clock: () -> Long = System::currentTimeMillis,
    private val monotonic: () -> Long = android.os.SystemClock::elapsedRealtime,
    private val sourceLock: Any = Any(),
    private val bookLock: Any = sourceLock
) {
    @Serializable private data class Binding(
        val format: Int = 12, val peerId: String, val runId: String, val publicKey: String,
        val sourceRevision: String, val restoreEpoch: String, val ownerEpoch: String,
        val ownerHash: String, val createdMs: Long, val expiresMs: Long,
        val createdMonotonicMs: Long, val expiresMonotonicMs: Long, val stopped: Boolean = false,
        val completionPhase: String = ""
    )
    private class CompletionSourceLost(message: String) : IllegalStateException(message)
    private val completionGuards = mutableMapOf<String, (String, JsonObject?) -> Boolean?>()
    private val dataRetired = mutableSetOf<String>()
    private val json = Json { encodeDefaults = true; ignoreUnknownKeys = false }
    init { require(HEX.matches(ownerEpoch)) }

    // Native service -> book -> SQLite, matching the existing snapshot/queue path.
    private inline fun <T> withNativeLocks(action: () -> T): T =
        synchronized(sourceLock) { synchronized(bookLock) { action() } }

    private fun key(peer: String, run: String): String = "personal_actor_journal:$peer:$run"
    private fun decode(id: String, sealed: ByteArray): Binding {
        val clear = storage.decryptPayload(sealed, "personal_actor_journal", id)
        return try {
            json.decodeFromString<Binding>(clear.decodeToString()).also {
                PersonalSyncActor.start(it.peerId); PersonalSyncActor.start(it.runId)
                TelefonKrypto.b64(it.publicKey, 32)
                require(it.format == 12 && id == key(it.peerId, it.runId) && HEX.matches(it.sourceRevision) &&
                    HEX.matches(it.ownerEpoch) && HEX.matches(it.ownerHash) &&
                    it.restoreEpoch.length <= 256 && it.createdMs >= 0 && it.expiresMs <= MAX_TIME &&
                    it.expiresMs - it.createdMs == LIFETIME && it.createdMonotonicMs >= 0 &&
                    it.expiresMonotonicMs > it.createdMonotonicMs &&
                     it.expiresMonotonicMs - it.createdMonotonicMs == LIFETIME &&
                     it.completionPhase in setOf("", "completion", "completed") && (it.completionPhase.isEmpty() || it.stopped))
            }
        } finally { clear.fill(0) }
    }
    private fun write(db: SQLiteDatabase, value: Binding) {
        val id = key(value.peerId, value.runId)
        val clear = json.encodeToString(value).encodeToByteArray()
        val sealed = try { storage.encryptPayload(clear, "personal_actor_journal", id) } finally { clear.fill(0) }
        db.insertWithOnConflict("meta", null, ContentValues().apply {
            put("key", id); put("value", sealed)
        }, SQLiteDatabase.CONFLICT_REPLACE).also { check(it != -1L) }
    }
    private fun requireOwner(db: SQLiteDatabase, handle: PersonalActorHandle, active: Boolean): Binding {
        require(HEX.matches(handle.token)) { "actor_not_found" }
        val id = key(handle.peerId, handle.runId)
        val binding = db.query("meta", arrayOf("value"), "key=?", arrayOf(id), null, null, null).use {
            check(it.moveToFirst()) { "actor_not_found" }; decode(id, it.getBlob(0))
        }
        check(binding.ownerEpoch == ownerEpoch && MessageDigest.isEqual(
            binding.ownerHash.encodeToByteArray(), hash(handle.token).encodeToByteArray())) { "actor_not_found" }
        if (active) {
            check(handle.runId !in dataRetired && !binding.stopped && clock() < binding.expiresMs && monotonic() < binding.expiresMonotonicMs &&
                clock() >= binding.createdMs && monotonic() >= binding.createdMonotonicMs) { "actor_inactive" }
            check(restoreEpoch() == binding.restoreEpoch &&
                currentSource(binding.peerId, binding.publicKey) == binding.sourceRevision) { "actor_source_changed" }
        }
        return binding
    }

    fun create(peerId: String, publicKey: String, sourceRevision: String,
               runId: String = UUID.randomUUID().toString()): PersonalActorHandle = withNativeLocks { database.writableDatabase.inTransaction {
        PersonalSyncActor.start(peerId); PersonalSyncActor.start(runId); TelefonKrypto.b64(publicKey, 32)
        require(HEX.matches(sourceRevision))
        val now = clock(); val elapsed = monotonic(); val restore = restoreEpoch()
        require(now in 0..(MAX_TIME - LIFETIME) && elapsed in 0..(Long.MAX_VALUE - LIFETIME) &&
            restore.length <= 256)
        check(currentSource(peerId, publicKey) == sourceRevision) { "actor_source_changed" }
        val rows = mutableListOf<Binding>()
        query("meta", arrayOf("key", "value"), "key GLOB ?", arrayOf("personal_actor_journal:*"), null, null, null).use {
            while (it.moveToNext()) rows += decode(it.getString(0), it.getBlob(1))
        }
        check(rows.none { it.runId == runId }) { "actor_identity_reused" }
        check(rows.size < 32 && rows.count { it.ownerEpoch == ownerEpoch && (!it.stopped || it.completionPhase == "completion") &&
            it.expiresMs > now && it.expiresMonotonicMs > elapsed } < 4) { "actor_capacity" }
        phoneCapacity("meta", 4096)
        val handle = PersonalActorHandle(peerId, runId, randomToken())
        write(this, Binding(peerId = peerId, runId = runId, publicKey = publicKey,
            sourceRevision = sourceRevision, restoreEpoch = restore, ownerEpoch = ownerEpoch,
            ownerHash = hash(handle.token), createdMs = now, expiresMs = now + LIFETIME,
            createdMonotonicMs = elapsed, expiresMonotonicMs = elapsed + LIFETIME))
        requireOwner(this, handle, true)
        handle
    } }

    /** Only same-database work belongs here; a rejected post-check rolls it back. */
    fun <T> withActive(handle: PersonalActorHandle, action: SQLiteDatabase.() -> T): T =
        withNativeLocks { database.writableDatabase.inTransaction {
            requireOwner(this, handle, true)
            action().also { requireOwner(this, handle, true) }
        } }

    fun stopped(handle: PersonalActorHandle): Boolean = withNativeLocks {
        requireOwner(database.readableDatabase, handle, false).stopped
    }

    private fun wireKey(handle: PersonalActorHandle, messageId: String): String =
        "personal_actor_wire:${handle.peerId}:${handle.runId}:$messageId"

    private fun completionWireKey(handle: PersonalActorHandle, messageId: String): String =
        "personal_actor_completion_wire:${handle.peerId}:${handle.runId}:$messageId"

    private fun wireUsage(db: SQLiteDatabase, handle: PersonalActorHandle): Pair<Long, Long> = db.rawQuery(
        "SELECT COUNT(*),COALESCE(SUM(length(value)),0) FROM meta WHERE key GLOB ? OR key GLOB ?",
        arrayOf(wireKey(handle, "*"), completionWireKey(handle, "*"))).use {
            check(it.moveToFirst()); it.getLong(0) to it.getLong(1)
        }

    private fun validateWire(handle: PersonalActorHandle, wire: JsonObject, fresh: Boolean) {
        TelefonNachrichten.validateHeader(wire, if (fresh) clock() else wire.long("created_ms"))
        val body = wire.getValue("body").jsonObject
        val maximum = when (wire.string("kind")) {
            PersonalSyncActor.DATA_KIND -> {
                PersonalSyncActor.validateData(body)
                val semantic = PersonalSyncActor.semanticMessage(wire)
                TelefonNachrichten.validate(semantic, if (fresh) clock() else wire.long("created_ms"))
                if (semantic.string("kind") == "personal_sync.request" ||
                    semantic.string("kind") == PhoneContentScope.DATA_KIND && semantic.getValue("body").jsonObject.string("kind") == "personal_sync.request")
                    3_600_000L else 86_400_000L
            }
            PersonalSyncActor.ACK_KIND -> { PersonalSyncActor.validateAck(body); 60_000L }
            PersonalSyncActor.START_KIND -> { PersonalSyncActor.validateStart(body); 60_000L }
            else -> error("Invalid raw actor kind")
        }
        require(body.string("run_id") == handle.runId && wire.long("expires_ms") <= MAX_TIME &&
            wire.long("expires_ms") - wire.long("created_ms") <= maximum &&
            (!fresh || wire.long("expires_ms") > clock()) && TelefonKanonisch.bytes(wire).size <= 256 * 1024)
    }

    /** Raw persistence/deduplication only. A stored frame does not authorize a successful wire ACK. */
    fun putWire(handle: PersonalActorHandle, wire: JsonObject): Boolean = withActive(handle) {
        validateWire(handle, wire, true)
        val id = wireKey(handle, wire.string("message_id")); val clear = TelefonKanonisch.bytes(wire)
        try {
            query("meta", arrayOf("value"), "key=?", arrayOf(id), null, null, null).use { row ->
                if (row.moveToFirst()) {
                    val old = storage.decryptPayload(row.getBlob(0), "personal_actor_wire", id)
                    try { check(MessageDigest.isEqual(old, clear)) { "actor_frame_conflict" } } finally { old.fill(0) }
                    return@withActive false
                }
            }
            val sealed = storage.encryptPayload(clear, "personal_actor_wire", id)
            val usage = wireUsage(this, handle)
            check(usage.first < 4096 && usage.second + sealed.size <= 50L * 1024 * 1024) { "actor_capacity" }
            phoneCapacity("meta", sealed.size)
            insertOrThrow("meta", null, ContentValues().apply { put("key", id); put("value", sealed) })
            true
        } finally { clear.fill(0) }
    }

    fun readWire(handle: PersonalActorHandle, messageId: String): JsonObject = withActive(handle) {
        TelefonNachrichten.uuid4(messageId)
        val id = wireKey(handle, messageId)
        query("meta", arrayOf("value"), "key=?", arrayOf(id), null, null, null).use {
            check(it.moveToFirst()) { "actor_packet_not_found" }
            val clear = storage.decryptPayload(it.getBlob(0), "personal_actor_wire", id)
            try {
                TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject.also { wire ->
                    validateWire(handle, wire, false)
                    check(wire.string("message_id") == messageId) { "actor_packet_identity" }
                }
            } finally { clear.fill(0) }
        }
    }

    private fun <T> completionOperation(handle: PersonalActorHandle, action: SQLiteDatabase.() -> T): T = withNativeLocks {
        try { database.writableDatabase.inTransaction { action() } }
        catch (error: CompletionSourceLost) {
            completionGuards.remove(handle.runId); dataRetired.add(handle.runId)
            try { retire(handle) } catch (_: Exception) { /* The volatile capability is already gone. */ }
            throw IllegalStateException(error.message)
        }
    }

    private fun requireCompletion(db: SQLiteDatabase, handle: PersonalActorHandle, operation: String, wire: JsonObject? = null): Binding {
        val binding = requireOwner(db, handle, false)
        check(binding.completionPhase in setOf("completion", "completed")) { "actor_completion_inactive" }
        if (restoreEpoch() != binding.restoreEpoch) throw CompletionSourceLost("actor_completion_source_changed")
        val wall = clock(); val mono = monotonic()
        if (wall < binding.createdMs || wall >= binding.expiresMs || mono < binding.createdMonotonicMs || mono >= binding.expiresMonotonicMs)
            throw CompletionSourceLost("actor_completion_inactive")
        val guard = completionGuards[handle.runId] ?: throw CompletionSourceLost("actor_completion_owner_lost")
        val result = try { guard(operation, wire) }
            catch (_: IllegalStateException) { throw CompletionSourceLost("actor_completion_source_changed") }
            catch (error: IllegalArgumentException) {
                if (wire != null) throw error
                throw CompletionSourceLost("actor_completion_source_changed")
            }
        check(result != null) { "actor_completion_not_ready" }
        if (result != true) throw CompletionSourceLost("actor_completion_source_changed")
        return binding
    }

    /** Native-only validator: true permits exactly that saved-claim/control/scope operation,
     * null waits, false retires. It must not perform document writes or network/GUI I/O. */
    fun beginCompletion(handle: PersonalActorHandle, nativeGuard: (String, JsonObject?) -> Boolean?): String {
        var installed = false
        try {
            completionOperation(handle) {
                val binding = requireOwner(this, handle, false)
                if (binding.completionPhase.isNotEmpty()) {
                    check(completionGuards[handle.runId] === nativeGuard) { "actor_completion_owner_changed" }
                    requireCompletion(this, handle, "begin")
                } else {
                    requireOwner(this, handle, true)
                    completionGuards[handle.runId] = nativeGuard; installed = true
                    write(this, binding.copy(stopped = true, completionPhase = "completion"))
                    requireCompletion(this, handle, "begin")
                    if (restoreEpoch() != binding.restoreEpoch || currentSource(binding.peerId, binding.publicKey) != binding.sourceRevision)
                        throw CompletionSourceLost("actor_completion_source_changed")
                    dataRetired.add(handle.runId)
                }
            }
        } catch (error: Throwable) {
            if (installed && completionGuards[handle.runId] === nativeGuard) completionGuards.remove(handle.runId)
            throw error
        }
        return completionState(handle)
    }

    private fun validateCompletionWire(handle: PersonalActorHandle, wire: JsonObject, fresh: Boolean) {
        require(wire.string("kind") == PersonalSyncActor.ACK_KIND ||
            wire.string("kind") == PersonalSyncActor.DATA_KIND && PersonalSyncActor.unwrap(wire.getValue("body").jsonObject).first == "personal_sync.deletion_decision") {
            "Completion storage accepts only deletion controls"
        }
        validateWire(handle, wire, fresh)
    }

    /** Raw persistence/deduplication only, not proof of a successful document save. */
    fun putCompletionControl(handle: PersonalActorHandle, wire: JsonObject): Boolean {
        validateCompletionWire(handle, wire, true)
        val clear = TelefonKanonisch.bytes(wire)
        try {
            val snapshot = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject
            val id = completionWireKey(handle, snapshot.string("message_id"))
            return completionOperation(handle) {
                requireCompletion(this, handle, "put", snapshot)
                query("meta", arrayOf("key"), "key=?", arrayOf(wireKey(handle, snapshot.string("message_id"))), null, null, null).use {
                    require(!it.moveToFirst()) { "actor_frame_conflict" }
                }
                query("meta", arrayOf("value"), "key=?", arrayOf(id), null, null, null).use { row ->
                    if (row.moveToFirst()) {
                        val previous = storage.decryptPayload(row.getBlob(0), "personal_actor_completion_wire", id)
                        try { require(MessageDigest.isEqual(previous, clear)) { "actor_frame_conflict" } } finally { previous.fill(0) }
                        requireCompletion(this, handle, "put", snapshot)
                        require(MessageDigest.isEqual(TelefonKanonisch.bytes(snapshot), clear)) { "actor_completion_callback_mutated_packet" }
                        return@completionOperation false
                    }
                }
                val sealed = storage.encryptPayload(clear, "personal_actor_completion_wire", id)
                val usage = wireUsage(this, handle)
                check(usage.first < 4096 && usage.second + sealed.size <= 50L * 1024 * 1024) { "actor_capacity" }
                phoneCapacity("meta", sealed.size)
                insertOrThrow("meta", null, ContentValues().apply { put("key", id); put("value", sealed) })
                requireCompletion(this, handle, "put", snapshot)
                require(MessageDigest.isEqual(TelefonKanonisch.bytes(snapshot), clear)) { "actor_completion_callback_mutated_packet" }
                true
            }
        } finally { clear.fill(0) }
    }

    fun readCompletionControls(handle: PersonalActorHandle): List<JsonObject> = completionOperation(handle) {
        requireCompletion(this, handle, "read")
        val result = mutableListOf<JsonObject>()
        query("meta", arrayOf("key", "value"), "key GLOB ?", arrayOf(completionWireKey(handle, "*")), null, null, "key").use { rows ->
            while (rows.moveToNext()) {
                val id = rows.getString(0)
                val clear = storage.decryptPayload(rows.getBlob(1), "personal_actor_completion_wire", id)
                try {
                    val wire = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject
                    validateCompletionWire(handle, wire, false)
                    require(id == completionWireKey(handle, wire.string("message_id")) && MessageDigest.isEqual(TelefonKanonisch.bytes(wire), clear))
                    result += wire
                } finally { clear.fill(0) }
            }
        }
        requireCompletion(this, handle, "read"); result
    }

    fun finishCompletion(handle: PersonalActorHandle): String {
        completionOperation(handle) {
            val binding = requireCompletion(this, handle, "finish")
            write(this, binding.copy(completionPhase = "completed"))
            requireCompletion(this, handle, "finish")
        }
        return completionState(handle)
    }

    fun completionState(handle: PersonalActorHandle): String = withNativeLocks {
        val binding = requireOwner(database.readableDatabase, handle, false)
        binding.completionPhase.ifEmpty { if (binding.stopped) "cancelled" else "active" }
    }

    /** Native retirement remains possible after revocation/expiry; it never authorizes content. */
    fun retire(handle: PersonalActorHandle, stopWork: SQLiteDatabase.() -> Unit = {}) = withNativeLocks { database.writableDatabase.inTransaction {
        val binding = requireOwner(this, handle, false)
        dataRetired.add(handle.runId); completionGuards.remove(handle.runId)
        stopWork()
        write(this, binding.copy(stopped = true, completionPhase = ""))
    } }

    /** Native maintenance only: never evict a live owner to make space for another request. */
    fun reapInactive(stopWork: SQLiteDatabase.(String, String) -> Unit): List<Pair<String, String>> = withNativeLocks {
        database.writableDatabase.inTransaction {
            val expired = mutableListOf<Binding>()
            query("meta", arrayOf("key", "value"), "key GLOB ?", arrayOf("personal_actor_journal:*"), null, null, null).use { rows ->
                while (rows.moveToNext()) {
                    val binding = decode(rows.getString(0), rows.getBlob(1))
                    if (binding.ownerEpoch != ownerEpoch || binding.expiresMs <= clock() || binding.expiresMonotonicMs <= monotonic())
                        expired += binding
                }
            }
            expired.forEach { binding ->
                completionGuards.remove(binding.runId); dataRetired.remove(binding.runId)
                stopWork(binding.peerId, binding.runId)
                delete("meta", "key GLOB ?", arrayOf("personal_actor_wire:${binding.peerId}:${binding.runId}:*"))
                delete("meta", "key GLOB ?", arrayOf("personal_actor_completion_wire:${binding.peerId}:${binding.runId}:*"))
                delete("meta", "key=?", arrayOf(key(binding.peerId, binding.runId)))
            }
            expired.map { it.peerId to it.runId }
        }
    }

    companion object {
        private const val LIFETIME = 30 * 60 * 1000L
        private const val MAX_TIME = 253402300799999L
        private val HEX = Regex("[0-9a-f]{64}")
        private fun randomToken(): String = ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        private fun hash(token: String): String = MessageDigest.getInstance("SHA-256").digest(token.encodeToByteArray()).joinToString("") { "%02x".format(it) }
    }
}
