package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.security.MessageDigest

internal data class SharedSettingsBinding(val localActor: String, val peerActor: String, val peerPublic: String)

/** Uses the existing phone database and Keystore-backed payload codec; creates no grants or outbox work. */
internal class SharedSyncStorage(
    private val database: () -> SQLiteDatabase,
    private val storage: TelefonPayloadStorage,
    private val binding: () -> SharedSettingsBinding?,
    private val restoreBlocked: () -> Boolean,
) {
    private fun key(expected: SharedSettingsBinding): String {
        check(binding() == expected) { "shared_settings_peer_changed" }
        TelefonNachrichten.uuid4(expected.localActor); TelefonNachrichten.uuid4(expected.peerActor)
        require(expected.localActor != expected.peerActor)
        val public = TelefonKrypto.b64(expected.peerPublic, 32)
        val hash = MessageDigest.getInstance("SHA-256").digest(public).joinToString("") { "%02x".format(it.toInt() and 255) }
        return "personal_shared_settings:${expected.peerActor}:${expected.localActor}:$hash:consent"
    }

    private fun read(db: SQLiteDatabase, key: String, expected: SharedSettingsBinding): JsonObject? =
        db.query("meta", arrayOf("value"), "key=?", arrayOf(key), null, null, null).use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val clear = storage.decryptPayload(cursor.getBlob(0), "shared_settings", key)
            try {
                val value = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                SharedSyncSettings.merge(value, value, expected.localActor, expected.peerActor)
                value
            } finally { clear.fill(0) }
        }

    @Synchronized fun read(expected: SharedSettingsBinding): JsonObject? {
        val key = key(expected)
        val value = read(database(), key, expected)
        check(key(expected) == key)
        return value
    }

    @Synchronized fun requireWritable(expected: SharedSettingsBinding) {
        check(!restoreBlocked()) { "restore_unavailable" }
        key(expected)
    }

    @Synchronized fun <T> withWriteTransaction(expected: SharedSettingsBinding, action: SQLiteDatabase.() -> T): T {
        requireWritable(expected)
        return database().inTransaction { action().also { requireWritable(expected) } }
    }

    @Synchronized private fun update(expected: SharedSettingsBinding, initial: Map<String, JsonElement>,
                                     apply: (JsonObject) -> JsonObject): JsonObject {
        check(!restoreBlocked()) { "restore_unavailable" }
        val key = key(expected)
        return database().inTransaction {
            val existing = read(this, key, expected)
            val previous = existing ?: SharedSyncSettings.create(expected.localActor, initial)
            val next = apply(previous)
            SharedSyncSettings.merge(next, next, expected.localActor, expected.peerActor)
            check(!restoreBlocked() && key(expected) == key) { "shared_settings_peer_changed" }
            if (existing == null || previous != next) {
                val clear = TelefonKanonisch.bytes(next)
                val sealed = try { storage.encryptPayload(clear, "shared_settings", key) } finally { clear.fill(0) }
                check(!restoreBlocked() && key(expected) == key) { "shared_settings_peer_changed" }
                insertWithOnConflict("meta", null, ContentValues().apply { put("key", key); put("value", sealed) },
                    SQLiteDatabase.CONFLICT_REPLACE).also { check(it != -1L) }
            }
            next
        }
    }

    fun initialize(expected: SharedSettingsBinding, initial: Map<String, JsonElement>) =
        update(expected, initial) { it }

    fun change(expected: SharedSettingsBinding, field: String, value: JsonElement, initial: Map<String, JsonElement> = emptyMap()) =
        update(expected, initial) { SharedSyncSettings.change(it, expected.localActor, expected.peerActor, field, value) }

    fun merge(expected: SharedSettingsBinding, incoming: JsonObject, initial: Map<String, JsonElement> = emptyMap()) =
        update(expected, initial) { SharedSyncSettings.merge(it, incoming, expected.localActor, expected.peerActor) }

    fun localContentScope(expected: SharedSettingsBinding, restoreEpoch: String, notes: Collection<String>, tasks: Collection<String>): JsonObject =
        withWriteTransaction(expected) {
            val key = key(expected).replaceFirst("personal_shared_settings:", "personal_local_scope:").removeSuffix(":consent")
            val previous = query("meta", arrayOf("value"), "key=?", arrayOf(key), null, null, null).use { cursor ->
                if (!cursor.moveToFirst()) return@use null
                val clear = storage.decryptPayload(cursor.getBlob(0), "local_content_scope", key)
                try {
                    val value = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject
                    TelefonNachrichten.exact(value, setOf("restore_epoch", "manifest"))
                    require((value["restore_epoch"] as? JsonPrimitive)?.isString == true)
                    PhoneContentScope.validate(value.getValue("manifest") as JsonObject)
                    value
                } finally { clear.fill(0) }
            }
            val old = previous?.get("manifest") as? JsonObject
            val manifest = when {
                old == null -> PhoneContentScope.create(notes, tasks)
                previous?.get("restore_epoch") != JsonPrimitive(restoreEpoch) -> PhoneContentScope.create(notes, tasks, old.long("revision") + 1)
                else -> PhoneContentScope.advance(old, notes, tasks)
            }
            if (manifest != old) {
                val value = buildJsonObject { put("restore_epoch", JsonPrimitive(restoreEpoch)); put("manifest", manifest) }
                val clear = TelefonKanonisch.bytes(value)
                val sealed = try { storage.encryptPayload(clear, "local_content_scope", key) } finally { clear.fill(0) }
                insertWithOnConflict("meta", null, ContentValues().apply { put("key", key); put("value", sealed) },
                    SQLiteDatabase.CONFLICT_REPLACE).also { check(it != -1L) }
            }
            manifest
        }
}
