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
        val createdMonotonicMs: Long, val expiresMonotonicMs: Long, val stopped: Boolean = false
    )
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
                    it.expiresMonotonicMs - it.createdMonotonicMs == LIFETIME)
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
            check(!binding.stopped && clock() < binding.expiresMs && monotonic() < binding.expiresMonotonicMs &&
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
        check(rows.size < 32 && rows.count { it.ownerEpoch == ownerEpoch && !it.stopped &&
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
            rawQuery("SELECT COUNT(*),COALESCE(SUM(length(value)),0) FROM meta WHERE key GLOB ?",
                arrayOf(wireKey(handle, "*"))).use {
                check(it.moveToFirst() && it.getLong(0) < 4096 && it.getLong(1) + sealed.size <= 50L * 1024 * 1024) { "actor_capacity" }
            }
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

    /** Native retirement remains possible after revocation/expiry; it never authorizes content. */
    fun retire(handle: PersonalActorHandle, stopWork: SQLiteDatabase.() -> Unit = {}) = withNativeLocks { database.writableDatabase.inTransaction {
        val binding = requireOwner(this, handle, false)
        stopWork()
        write(this, binding.copy(stopped = true))
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
                stopWork(binding.peerId, binding.runId)
                delete("meta", "key GLOB ?", arrayOf("personal_actor_wire:${binding.peerId}:${binding.runId}:*"))
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
