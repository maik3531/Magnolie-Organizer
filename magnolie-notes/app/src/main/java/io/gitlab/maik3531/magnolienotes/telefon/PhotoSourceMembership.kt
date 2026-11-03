package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest
import java.util.Locale

/** Exact aggregate of actual protected rows, not a read grant or backup clock.
 * The native index owns its OS lock and the only writable SQL transaction.
 * Advancing a head is permitted only within that exact thread/transaction lease.
 */
internal class PhotoSourceMembership(private val db: SQLiteDatabase, private val rootKey: String,
    private val databaseKey: String, private val decode: (String, ByteArray) -> PhotoSourceJob,
    private val seal: (JsonObject) -> ByteArray, private val open: (ByteArray) -> JsonObject) {
    private var last: Pair<Long, String>? = null
    private var held: Pair<Thread, String>? = null

    fun initialize() {
        if (!db.inTransaction() || blob() != null) fail("photo_jobs_membership_bootstrap_invalid")
        put(seal(value(1)))
    }

    fun verify(): Long {
        val bytes = blob() ?: fail("photo_jobs_membership_missing")
        val record = open(bytes)
        val revision = (record["revision"] as? JsonPrimitive)?.takeIf {
            !it.isString && Regex("[1-9][0-9]*").matches(it.content)
        }?.content?.toLongOrNull()?.takeIf { it < Long.MAX_VALUE } ?: fail("photo_jobs_membership_invalid")
        if (!TelefonKanonisch.bytes(record).contentEquals(TelefonKanonisch.bytes(value(revision))))
            fail("photo_jobs_membership_changed")
        val mark = revision to digest(bytes)
        last?.let { if (revision < it.first || revision == it.first && mark != it) fail("photo_jobs_membership_rollback") }
        // A rolled-back SQL head was never a committed observation. Nested
        // native policy checks still authenticate all actual rows every time.
        if (!db.inTransaction()) last = mark
        return revision
    }

    fun begin() {
        if (held != null || db.inTransaction()) fail("photo_jobs_membership_transaction_busy")
        verify(); held = Thread.currentThread() to digest(blob()!!)
    }

    fun advance() {
        val lease = held ?: fail("photo_jobs_membership_transaction_required")
        if (lease.first !== Thread.currentThread() || !db.inTransaction()) fail("photo_jobs_membership_transaction_required")
        val original = blob() ?: fail("photo_jobs_membership_missing")
        if (digest(original) != lease.second) fail("photo_jobs_membership_cas_changed")
        val previous = open(original)
        val revision = (previous["revision"] as? JsonPrimitive)?.content?.toLongOrNull()
            ?.takeIf { it in 1 until Long.MAX_VALUE - 1 } ?: fail("photo_jobs_membership_invalid")
        val next = seal(value(revision + 1))
        put(next); held = lease.first to digest(next)
        verify()
    }

    fun end() { held = null }

    private fun value(revision: Long): JsonObject {
        val schema = mutableMapOf<String, String>()
        val auto = mapOf("sqlite_autoindex_source_meta_1" to "source_meta", "sqlite_autoindex_source_jobs_1" to "source_jobs")
        val seen = mutableSetOf<String>()
        db.rawQuery("SELECT type,name,tbl_name,sql FROM sqlite_master", null).use {
            while (it.moveToNext()) {
                val type = it.getString(0); val name = it.getString(1); val table = it.getString(2)
                val sql = if (it.isNull(3)) null else it.getString(3).replace(Regex("\\s+"), "")
                when {
                    name in auto -> {
                        if (type != "index" || table != auto[name] || sql != null) fail("photo_jobs_membership_schema_changed")
                        seen += name
                    }
                    name == "android_metadata" -> if (type != "table" || table != name || sql != "CREATETABLEandroid_metadata(localeTEXT)")
                        fail("photo_jobs_membership_schema_changed")
                    name in setOf("source_meta", "source_jobs") -> {
                        if (type != "table" || table != name || sql == null) fail("photo_jobs_membership_schema_changed")
                        schema[name] = sql
                    }
                    else -> fail("photo_jobs_membership_schema_changed")
                }
            }
        }
        if (seen != auto.keys || schema != mapOf("source_meta" to "CREATETABLEsource_meta(nameTEXTPRIMARYKEYNOTNULL,sealedBLOBNOTNULL)",
                "source_jobs" to "CREATETABLEsource_jobs(job_idTEXTPRIMARYKEYNOTNULL,sealedBLOBNOTNULL)"))
            fail("photo_jobs_membership_schema_changed")
        val members = mutableListOf<JsonObject>(); var plain = 0L; var budget = 0L
        db.query("source_jobs", arrayOf("job_id", "sealed"), null, null, null, null, "job_id").use {
            while (it.moveToNext()) {
                if (members.size >= PhotoSourceJobIndex.MAX_JOBS) fail("photo_jobs_unbounded_index")
                val id = it.getString(0); val bytes = it.getBlob(1); val job = decode(id, bytes)
                plain += job.plainBytes; budget += job.cipherBudget
                members += JsonObject(mapOf("id" to JsonPrimitive(id), "sha256" to JsonPrimitive(digest(bytes))))
            }
        }
        if (plain > DeviceFileManifest.MAX_TOTAL_BYTES || budget > PhotoSourceJobIndex.MAX_CIPHER_BYTES)
            fail("photo_jobs_membership_quota_changed")
        val metadata = mutableListOf<JsonObject>()
        db.query("source_meta", arrayOf("name", "sealed"), "name<>?", arrayOf(NAME), null, null, "name").use {
            while (it.moveToNext()) {
                val name = it.getString(0)
                val remoteJob = if (name.startsWith("remote-saved-v1/")) name.removePrefix("remote-saved-v1/") else null
                if ((name !in setOf("format", "gallery-policy-v1", "gallery-policy-v1-repair") &&
                    (remoteJob == null || members.none { member -> member["id"] == JsonPrimitive(remoteJob) })) ||
                    metadata.size >= 3 + PhotoSourceJobIndex.MAX_JOBS)
                    fail("photo_jobs_membership_unknown_metadata")
                val bytes = it.getBlob(1)
                if (bytes.size !in 28..DeviceTransferProtection.MAX_CLEAR_BYTES + 28) fail("photo_jobs_membership_invalid")
                metadata += JsonObject(mapOf("name" to JsonPrimitive(name), "sha256" to JsonPrimitive(digest(bytes))))
            }
        }
        return JsonObject(mapOf("format" to JsonPrimitive(1), "root_key" to JsonPrimitive(rootKey),
            "database_key" to JsonPrimitive(databaseKey), "revision" to JsonPrimitive(revision),
            "count" to JsonPrimitive(members.size), "plain_bytes" to JsonPrimitive(plain), "cipher_budget" to JsonPrimitive(budget),
            "members_sha256" to JsonPrimitive(digest(TelefonKanonisch.bytes(JsonArray(members)))),
            "metadata_count" to JsonPrimitive(metadata.size), "metadata_sha256" to JsonPrimitive(digest(TelefonKanonisch.bytes(JsonArray(metadata))))))
    }

    private fun blob(): ByteArray? = db.query("source_meta", arrayOf("sealed"), "name=?", arrayOf(NAME), null, null, null).use {
        if (!it.moveToFirst()) null else it.getBlob(0).also { bytes ->
            if (bytes.size !in 28..8192 || it.moveToNext()) fail("photo_jobs_membership_invalid")
        }
    }
    private fun put(bytes: ByteArray) {
        if (bytes.size !in 28..8192) fail("photo_jobs_membership_invalid")
        db.insertWithOnConflict("source_meta", null, ContentValues().apply { put("name", NAME); put("sealed", bytes) }, SQLiteDatabase.CONFLICT_REPLACE)
            .also { if (it == -1L) fail("photo_jobs_membership_write_failed") }
    }
    companion object {
        const val NAME = "membership-v1"
        private fun digest(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
