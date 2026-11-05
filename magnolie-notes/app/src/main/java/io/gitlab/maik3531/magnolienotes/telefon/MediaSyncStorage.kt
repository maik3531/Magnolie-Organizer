package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import kotlinx.serialization.json.*

internal data class MediaSettingsBinding(val localActor: String, val localKey: String,
    val peerActor: String, val peerKey: String, val pairingEpoch: String)

/** Durable media intent only: never Android permission, source policy or an outbox job. */
internal class MediaSyncStorage(
    private val database: () -> SQLiteDatabase,
    private val storage: TelefonPayloadStorage,
    private val binding: () -> MediaSettingsBinding?,
    private val restoreBlocked: () -> Boolean,
    private val legacyProjection: (MediaSettingsBinding) -> JsonObject = { MediaSyncSettings.create(it.localActor) },
) {
    private fun scope(expected: MediaSettingsBinding): String {
        check(!restoreBlocked()) { "media_shared_restore_fenced" }
        check(binding() == expected) { "media_shared_peer_changed" }
        TelefonNachrichten.uuid4(expected.localActor); TelefonNachrichten.uuid4(expected.peerActor)
        require(expected.localActor != expected.peerActor && DeviceFileControl.hash(expected.localKey) &&
            DeviceFileControl.hash(expected.peerKey) && DeviceFileControl.hash(expected.pairingEpoch))
        return DeviceFileControl.digest("magnolie-media-shared-scope-v1\u0000", buildJsonObject {
            put("local_id", expected.localActor); put("local_key", expected.localKey)
            put("peer_id", expected.peerActor); put("peer_key", expected.peerKey); put("pairing_epoch", expected.pairingEpoch)
        })
    }

    private fun read(db: SQLiteDatabase, expected: MediaSettingsBinding, scope: String): JsonObject? {
        db.rawQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_shared_settings'", null).use {
            if (!it.moveToFirst()) return null
        }
        return db.query("native_media_shared_settings", arrayOf("value"), "peer_id=?", arrayOf(expected.peerActor),
            null, null, null).use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val encrypted = cursor.getBlob(0); require(encrypted.size <= 32768)
            val clear = storage.decryptPayload(encrypted, "native_media_shared_settings", expected.peerActor)
            try {
                val record = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject
                TelefonNachrichten.exact(record, setOf("format", "scope", "body"))
                require(record["format"] == JsonPrimitive(1) && record["scope"] == JsonPrimitive(scope))
                val body = record.getValue("body").jsonObject
                MediaSyncSettings.merge(body, body, expected.localActor, expected.peerActor)
                body
            } finally { clear.fill(0) }
        }
    }

    @Synchronized fun read(expected: MediaSettingsBinding): JsonObject? {
        val scope = scope(expected)
        return read(database(), expected, scope).also { check(scope(expected) == scope) }
    }

    @Synchronized fun project(expected: MediaSettingsBinding): JsonObject {
        val scope = scope(expected)
        val body = read(database(), expected, scope) ?: legacyProjection(expected)
        MediaSyncSettings.merge(body, body, expected.localActor, expected.peerActor)
        check(scope(expected) == scope)
        return body
    }

    private fun fieldVersion(scope: String, body: JsonObject, field: String): String =
        DeviceFileControl.digest("magnolie-media-shared-field-view-v1\u0000", JsonArray(listOf(JsonPrimitive(scope),
            JsonPrimitive(field), body.getValue("settings").jsonObject.getValue(field))))

    @Synchronized fun fieldVersion(expected: MediaSettingsBinding, field: String): String =
        fieldVersion(scope(expected), project(expected), field)

    @Synchronized private fun update(expected: MediaSettingsBinding, apply: (JsonObject, String) -> JsonObject): JsonObject {
        val scope = scope(expected)
        val db = database()
        val next = db.inTransaction {
            val existing = read(this, expected, scope)
            val previous = existing ?: legacyProjection(expected)
            MediaSyncSettings.merge(previous, previous, expected.localActor, expected.peerActor)
            val next = apply(previous, scope)
            MediaSyncSettings.merge(next, next, expected.localActor, expected.peerActor)
            check(scope(expected) == scope)
            if (existing != next) {
                val clear = TelefonKanonisch.bytes(buildJsonObject { put("format", 1); put("scope", scope); put("body", next) })
                val encrypted = try { storage.encryptPayload(clear, "native_media_shared_settings", expected.peerActor) }
                    finally { clear.fill(0) }
                check(scope(expected) == scope)
                execSQL("CREATE TABLE IF NOT EXISTS native_media_shared_settings(peer_id TEXT PRIMARY KEY, value BLOB NOT NULL)")
                insertWithOnConflict("native_media_shared_settings", null, ContentValues().apply {
                    put("peer_id", expected.peerActor); put("value", encrypted)
                }, SQLiteDatabase.CONFLICT_REPLACE).also { check(it != -1L) }
            }
            next
        }
        check(read(db, expected, scope) == next && scope(expected) == scope) { "media_shared_commit_not_proven" }
        return next
    }

    fun change(expected: MediaSettingsBinding, field: String, value: JsonElement, expectedVersion: String): JsonObject =
        update(expected) { body, scope ->
            check(DeviceFileControl.hash(expectedVersion) && fieldVersion(scope, body, field) == expectedVersion) {
                "media_shared_stale_field_choice"
            }
            MediaSyncSettings.change(body, expected.localActor, expected.peerActor, field, value)
        }

    fun merge(expected: MediaSettingsBinding, incoming: JsonObject): JsonObject = update(expected) { body, _ ->
        MediaSyncSettings.mergeCurrentChoices(body, incoming, expected.localActor, expected.peerActor)
    }
}
