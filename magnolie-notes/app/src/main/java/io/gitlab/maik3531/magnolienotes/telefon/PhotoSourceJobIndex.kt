package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.os.CancellationSignal
import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardOpenOption.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.util.Locale
import java.util.UUID

internal data class PhotoSourceJob internal constructor(val id: String, val version: String,
    val sourceContext: String, val plainBytes: Long, val cipherBudget: Long,
    val rootKey: String?, val phase: String, val snapshot: JsonObject?)

internal class IndexedPhotoSource internal constructor(private val index: PhotoSourceJobIndex,
    val job: PhotoSourceJob, private val scope: NativePhotoSourceAuthority, private val lease: NativePhotoSourceLease,
    private val snapshot: ProtectedPhotoSourceSnapshot) {
    val manifest: DeviceFileManifest get() = index.withSealedHead(job, scope, lease) { snapshot.manifest }
    fun readChunk(fileId: String, chunk: Int): ByteArray = index.withSealedHead(job, scope, lease) { snapshot.readChunk(fileId, chunk) }
    /** Preflight only; the actual send handler must recheck live negotiated
     * authority. Returning an envelope does not preserve consent after revoke.
     */
    fun offerMessage(now: Long = System.currentTimeMillis(), messageId: String = UUID.randomUUID().toString()): JsonObject =
        index.withSealedHead(job, scope, lease) { DeviceFileOfferEnvelope.create(snapshot.manifest, now, messageId) }
    fun retireAndDiscard() = index.retireAndClean(job) { snapshot.discard() }
}

/** Dedicated source-job DB only. Never opens/migrates the personal phone DB.
 * Retired/uncertain jobs retain both quota and their actual persisted metadata.
 */
internal class PhotoSourceJobIndex(private val directory: File, private val protection: DeviceTransferProtection,
    private val boundary: (String) -> Unit = {}) : AutoCloseable {
    private val root = directory.toPath()
    private val rootKey: Any = attributes(directory).fileKey() ?: fail("photo_jobs_root_identity_unavailable")
    private val path = File(directory, "photo-source-jobs.db")
    private lateinit var db: SQLiteDatabase
    private lateinit var dbKey: Any
    private var closed = false

    init {
        require(directory.isAbsolute && directory.canonicalFile == directory)
        gated {
            val exists = Files.exists(path.toPath(), NOFOLLOW_LINKS)
            val preparedHeader = if (!exists) {
                Files.newDirectoryStream(root).use { entries ->
                    if (entries.any { it.fileName.toString() != "photo-source-jobs.lock" }) fail("photo_jobs_missing_index_preserved")
                }
                protection.seal(HEADER.toByteArray(Charsets.US_ASCII), "photo-source-jobs-v1/header")
            } else null
            if (exists) regular(path) else Files.createFile(path.toPath(), PRIVATE_FILE)
            sidecars()
            db = SQLiteDatabase.openDatabase(path.path, null, SQLiteDatabase.OPEN_READWRITE or SQLiteDatabase.NO_LOCALIZED_COLLATORS)
            try {
                dbKey = attributes(path).fileKey() ?: fail("photo_jobs_db_identity_unavailable")
                if (exists) verifyHeader()
                db.enableWriteAheadLogging()
                db.execSQL("PRAGMA synchronous=FULL")
                db.rawQuery("PRAGMA wal_autocheckpoint=256", null).use { if (!it.moveToFirst()) fail("photo_jobs_wal_configuration_failed") }
                if (!exists) {
                    transaction {
                        db.execSQL("CREATE TABLE source_meta(name TEXT PRIMARY KEY NOT NULL, sealed BLOB NOT NULL)")
                        db.execSQL("CREATE TABLE source_jobs(job_id TEXT PRIMARY KEY NOT NULL, sealed BLOB NOT NULL)")
                        db.insertOrThrow("source_meta", null, ContentValues().apply { put("name", "format"); put("sealed", preparedHeader!!) })
                    }
                    synchronisiereOrdner(directory)
                }
                verifyHeader()
            } catch (error: Exception) { db.close(); closed = true; throw error }
        }
    }

    /** Durable encrypted reservation/readback BEFORE creating any source root. */
    fun reserve(inventory: PhotoSourceInventory, scope: NativePhotoSourceAuthority): PhotoSourceJob = gated {
        val lease = inventory.lease
        fun allowed() { if (!scope.isCurrent(lease)) fail("photo_jobs_source_revoked") }
        allowed()
        if (inventory.entries.size !in 1..DeviceFileManifest.MAX_FILES) fail("photo_jobs_inventory_limit")
        var plain = 0L; var chunks = 0L; var empty = 0L
        inventory.entries.forEach {
            if (it.advertisedBytes !in 0..DeviceFileManifest.MAX_FILE_BYTES || !DeviceFileManifest.portablePath(it.relativePath))
                fail("photo_jobs_inventory_limit")
            plain += it.advertisedBytes
            chunks += (it.advertisedBytes + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES
            if (it.advertisedBytes == 0L) empty++
        }
        if (plain > DeviceFileManifest.MAX_TOTAL_BYTES) fail("photo_jobs_source_bytes_limit")
        val budget = plain + chunks * 29L + empty * 29L + 2 * (262144L + 28L)
        val id = UUID.randomUUID().toString().replace("-", "")
        val next = PhotoSourceJob(id, "", context(lease), plain, budget, null, "reserved", null)
        transaction {
            val jobs = readAll()
            validateLayout(jobs)
            if (jobs.size >= MAX_JOBS || jobs.sumOf { it.plainBytes } + plain > DeviceFileManifest.MAX_TOTAL_BYTES ||
                jobs.sumOf { it.cipherBudget } + budget > MAX_CIPHER_BYTES) fail("photo_jobs_quota_reached")
            allowed()
            insert(next)
            allowed()
        }
        val reserved = readOne(id) ?: fail("photo_jobs_reservation_readback_missing")
        if (data(reserved) != data(next)) fail("photo_jobs_reservation_readback_changed")
        boundary("reservation-committed")
        allowed()
        val child = rootFile(reserved)
        Files.createDirectory(child.toPath(), PRIVATE_DIRECTORY)
        synchronisiereOrdner(directory)
        allowed()
        update(reserved, reserved.copy(rootKey = attributes(child).fileKey()?.toString()
            ?: fail("photo_jobs_child_identity_unavailable")), ::allowed)
    }

    fun jobs(): List<PhotoSourceJob> = gated { readAll() }

    fun restore(expected: PhotoSourceJob, senderId: String, scope: NativePhotoSourceAuthority, lease: NativePhotoSourceLease,
        cancellation: CancellationSignal = CancellationSignal()): IndexedPhotoSource = withSealedHead(expected, scope, lease) {
        val actual = readOne(expected.id) ?: fail("photo_jobs_missing_job")
        val snapshot = ProtectedPhotoSourceSnapshot.restore(rootFile(actual), actual.snapshot ?: fail("photo_jobs_snapshot_missing"),
            senderId, scope, lease, protection, cancellation)
        IndexedPhotoSource(this, actual, scope, lease, snapshot)
    }

    internal fun <T> withSealedHead(expected: PhotoSourceJob, scope: NativePhotoSourceAuthority, lease: NativePhotoSourceLease, action: () -> T): T = gated {
        fun check() {
            verifyHeader()
            val current = readOne(expected.id) ?: fail("photo_jobs_missing_job")
            if (current.version != expected.version || data(current) != data(expected) || current.phase != "sealed")
                fail("photo_jobs_sealed_head_changed")
            if (!scope.isCurrent(lease) || current.sourceContext != context(lease)) fail("photo_jobs_source_revoked")
            if (attributes(rootFile(current)).fileKey()?.toString() != current.rootKey) fail("photo_jobs_root_changed")
        }
        check()
        val result = action()
        try { check(); result } catch (error: Exception) { if (result is ByteArray) result.fill(0); throw error }
    }

    fun rootFile(job: PhotoSourceJob): File {
        if (!ID.matches(job.id)) fail("photo_jobs_invalid_id")
        return File(directory, "photo-source-" + job.id)
    }

    /** Only an actual verified snapshot object may be passed, never an IPC payload. */
    internal fun publishSnapshot(expected: PhotoSourceJob, snapshot: ProtectedPhotoSourceSnapshot, scope: NativePhotoSourceAuthority,
        lease: NativePhotoSourceLease): PhotoSourceJob = gated {
        fun allowed() {
            if (!scope.isCurrent(lease) || expected.sourceContext != context(lease)) fail("photo_jobs_source_revoked")
        }
        allowed()
        if (expected.phase != "reserved" || expected.rootKey == null ||
            attributes(rootFile(expected)).fileKey()?.toString() != expected.rootKey) fail("photo_jobs_root_changed")
        if (snapshot.lease !== lease || snapshot.manifest.totalBytes != expected.plainBytes) fail("photo_jobs_snapshot_binding_changed")
        val record = snapshot.nativeRecord()
        val actualBytes = (record["cipher_bytes"] as? JsonPrimitive)?.content?.toLongOrNull() ?: fail("photo_jobs_invalid_snapshot")
        if (record["root_key"] != JsonPrimitive(expected.rootKey) || actualBytes > expected.cipherBudget)
            fail("photo_jobs_snapshot_reservation_exceeded")
        update(expected, expected.copy(phase = "sealed", snapshot = record), ::allowed)
    }

    /** Explicit local-cache retirement, including obsolete/revoked gallery
     * scopes. Does not restore source access or accept a remote cleanup record.
     * Reserved/partial jobs without authenticated original witnesses stay held.
     */
    fun retireCachedSnapshot(expected: PhotoSourceJob) {
        if (expected.snapshot == null) fail("photo_cache_snapshot_missing")
        retireAndClean(expected) {
            val retired = readOne(expected.id) ?: fail("photo_jobs_missing_job")
            ProtectedPhotoCacheCleanup.discard(rootFile(retired), retired, boundary)
        }
    }

    /** Commit retirement first; retain quota on ANY cleanup failure.
     * A retry uses the actually re-read retired head, not a stale caller head.
     */
    fun retireAndClean(expected: PhotoSourceJob, cleanup: () -> Unit) = gated {
        val observed = readOne(expected.id) ?: fail("photo_jobs_missing_job")
        if (observed.version != expected.version || data(observed) != data(expected)) fail("photo_jobs_cas_conflict")
        val retired = if (observed.phase == "retired") observed else update(observed, observed.copy(phase = "retired")) { }
        val child = rootFile(retired)
        if (Files.exists(child.toPath(), NOFOLLOW_LINKS)) {
            if (retired.rootKey == null || attributes(child).fileKey()?.toString() != retired.rootKey) fail("photo_jobs_unknown_root_preserved")
            cleanup()
        }
        if (Files.exists(child.toPath(), NOFOLLOW_LINKS)) fail("photo_jobs_cleanup_not_proven")
        synchronisiereOrdner(directory)
        boundary("cleanup-proven")
        transaction {
            val current = readOne(retired.id) ?: fail("photo_jobs_missing_job")
            if (current.version != retired.version) fail("photo_jobs_cas_conflict")
            if (db.delete("source_jobs", "job_id=?", arrayOf(retired.id)) != 1) fail("photo_jobs_retirement_failed")
        }
        if (readOne(retired.id) != null) fail("photo_jobs_retirement_readback_failed")
    }

    private fun update(expected: PhotoSourceJob, wanted: PhotoSourceJob, permitted: () -> Unit = {}): PhotoSourceJob {
        val cipher = protect(wanted)
        transaction {
            val current = readOne(expected.id) ?: fail("photo_jobs_missing_job")
            if (current.version != expected.version || data(current) != data(expected)) fail("photo_jobs_cas_conflict")
            permitted()
            if (db.update("source_jobs", ContentValues().apply { put("sealed", cipher) }, "job_id=?", arrayOf(expected.id)) != 1)
                fail("photo_jobs_update_failed")
            permitted()
        }
        boundary("job-head-committed")
        val saved = readOne(expected.id) ?: fail("photo_jobs_update_readback_missing")
        if (saved.version != hash(cipher) || data(saved) != data(wanted)) fail("photo_jobs_update_readback_changed")
        permitted()
        return saved
    }
    private fun insert(value: PhotoSourceJob) {
        db.insertOrThrow("source_jobs", null, ContentValues().apply { put("job_id", value.id); put("sealed", protect(value)) })
    }
    private fun protect(value: PhotoSourceJob) = protection.seal(frame(data(value)), "photo-source-jobs-v1/job/" + value.id)
    private fun readOne(id: String): PhotoSourceJob? = db.query("source_jobs", arrayOf("job_id", "sealed"), "job_id=?", arrayOf(id), null, null, null).use {
        if (!it.moveToFirst()) null else decode(it.getString(0), it.getBlob(1))
    }
    private fun readAll(): List<PhotoSourceJob> {
        verifyHeader()
        val jobs = mutableListOf<PhotoSourceJob>()
        db.query("source_jobs", arrayOf("job_id", "sealed"), null, null, null, null, "job_id").use {
            while (it.moveToNext()) {
                if (jobs.size >= MAX_JOBS) fail("photo_jobs_unbounded_index")
                jobs += decode(it.getString(0), it.getBlob(1))
            }
        }
        return jobs
    }
    private fun decode(id: String, cipher: ByteArray): PhotoSourceJob {
        if (!ID.matches(id)) fail("photo_jobs_invalid_id")
        val value = parse(protection.open(cipher, "photo-source-jobs-v1/job/$id"))
        if (value.keys != setOf("format", "source_context", "plain_bytes", "cipher_budget", "root_key", "phase", "snapshot") ||
            value["format"] != JsonPrimitive(1)) fail("photo_jobs_invalid_record")
        fun text(key: String) = (value[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail("photo_jobs_invalid_record")
        fun integer(key: String): Long = (value[key] as? JsonPrimitive)?.takeIf { !it.isString && Regex("0|[1-9][0-9]*").matches(it.content) }
            ?.content?.toLongOrNull() ?: fail("photo_jobs_invalid_record")
        val plain = integer("plain_bytes"); val budget = integer("cipher_budget"); val phase = text("phase")
        val key = if (value["root_key"] == JsonNull) null else text("root_key")
        val snapshot = if (value["snapshot"] == JsonNull) null else value["snapshot"] as? JsonObject ?: fail("photo_jobs_invalid_record")
        if (plain !in 0..DeviceFileManifest.MAX_TOTAL_BYTES || budget !in plain..MAX_CIPHER_BYTES ||
            phase !in setOf("reserved", "sealed", "retired") || !SHA.matches(text("source_context")) ||
            (key != null && key.length !in 1..512) || phase == "sealed" && (key == null || snapshot == null)) fail("photo_jobs_invalid_record")
        return PhotoSourceJob(id, hash(cipher), text("source_context"), plain, budget, key, phase, snapshot)
    }
    private fun verifyHeader() {
        db.query("source_meta", arrayOf("sealed"), "name=?", arrayOf("format"), null, null, null).use {
            if (!it.moveToFirst() || !protection.open(it.getBlob(0), "photo-source-jobs-v1/header").contentEquals(HEADER.toByteArray(Charsets.US_ASCII)))
                fail("photo_jobs_header_invalid")
        }
    }
    private fun <T> transaction(action: () -> T): T {
        db.beginTransaction()
        try { val result = action(); db.setTransactionSuccessful(); return result } finally { db.endTransaction() }
    }
    private fun checkDirectory() {
        if (closed || !attributes(directory).isDirectory || attributes(directory).fileKey() != rootKey || directory.canonicalFile != directory)
            fail("photo_jobs_directory_changed")
        if (Files.getPosixFilePermissions(root, NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") })
            fail("photo_jobs_private_directory_required")
    }
    private fun regular(file: File) {
        if (!attributes(file).isRegularFile || Files.getOwner(file.toPath(), NOFOLLOW_LINKS) != Files.getOwner(root, NOFOLLOW_LINKS) ||
            Files.getPosixFilePermissions(file.toPath(), NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") } ||
            (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1) fail("photo_jobs_unsafe_entry")
    }
    private fun validateLayout(jobs: List<PhotoSourceJob>) {
        val roots = jobs.associateBy { rootFile(it).name }
        val indexNames = setOf(path.name, path.name + "-wal", path.name + "-shm", path.name + "-journal", "photo-source-jobs.lock")
        Files.newDirectoryStream(root).use { entries ->
            for (entry in entries) {
                val name = entry.fileName.toString()
                if (name in indexNames) regular(entry.toFile())
                else {
                    val job = roots[name] ?: fail("photo_jobs_unindexed_entries_preserved")
                    val actual = attributes(entry.toFile())
                    if (!actual.isDirectory || job.rootKey == null || actual.fileKey()?.toString() != job.rootKey)
                        fail("photo_jobs_unknown_root_preserved")
                    var count = 0L; var bytes = 0L
                    val maximum = (job.plainBytes + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES + DeviceFileManifest.MAX_FILES + 2
                    Files.newDirectoryStream(entry).use { children ->
                        for (child in children) {
                            if (++count > maximum) fail("photo_jobs_root_budget_exceeded")
                            val childName = child.fileName.toString()
                            if (childName !in setOf("owner.enc", "manifest.enc") &&
                                !Regex("empty-[0-9a-f]{32}\\.enc|[0-9a-f]{32}-(0|[1-9][0-9]{0,3})\\.enc").matches(childName))
                                fail("photo_jobs_unfamiliar_root_entry")
                            if (job.snapshot != null && (job.snapshot["files"] as? kotlinx.serialization.json.JsonArray)?.none {
                                    (it as? JsonObject)?.get("name") == JsonPrimitive(childName) } != false)
                                fail("photo_jobs_unfamiliar_root_entry")
                            regular(child.toFile())
                            bytes += attributes(child.toFile()).size()
                            if (bytes > job.cipherBudget) fail("photo_jobs_root_budget_exceeded")
                        }
                    }
                }
            }
        }
    }
    private fun sidecars() {
        listOf("-wal", "-shm", "-journal").forEach {
            val file = File(path.path + it)
            if (Files.exists(file.toPath(), NOFOLLOW_LINKS)) regular(file)
        }
    }
    private fun <T> gated(action: () -> T): T = synchronized(gate) {
        checkDirectory()
        val lock = File(directory, "photo-source-jobs.lock")
        if (Files.exists(lock.toPath(), NOFOLLOW_LINKS)) regular(lock)
        FileChannel.open(lock.toPath(), setOf(WRITE, CREATE, NOFOLLOW_LINKS), PRIVATE_FILE).use { channel ->
            channel.lock().use {
                checkDirectory()
                if (::dbKey.isInitialized) {
                    regular(path)
                    sidecars()
                    if (attributes(path).fileKey() != dbKey) fail("photo_jobs_db_replaced")
                }
                action()
            }
        }
    }
    override fun close() = synchronized(gate) { if (!closed) { closed = true; if (::db.isInitialized) db.close() } }

    companion object {
        const val MAX_JOBS = 8
        const val MAX_CIPHER_BYTES = DeviceFileManifest.MAX_TOTAL_BYTES + 8L * 1024 * 1024
        private val gate = Any()
        private val ID = Regex("[0-9a-f]{32}")
        private val SHA = Regex("[0-9a-f]{64}")
        private const val HEADER = "magnolie-private-photo-source-jobs-v1"
        private val PRIVATE_FILE = PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))
        private val PRIVATE_DIRECTORY = PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))
        private fun attributes(file: File) = Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS)
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        private fun context(lease: NativePhotoSourceLease) = hash(TelefonKanonisch.bytes(JsonObject(mapOf(
            "tree" to JsonPrimitive(lease.sourceKey), "version" to JsonPrimitive(lease.version),
            "epoch" to JsonPrimitive(lease.sourceEpoch), "receiver" to JsonPrimitive(lease.receiver.peerId),
            "identity" to JsonPrimitive(lease.receiver.identitySha256), "permission_epoch" to JsonPrimitive(lease.receiver.permissionEpoch),
            "read_grant" to JsonPrimitive(lease.readGrantToken)))))
        private fun data(value: PhotoSourceJob) = JsonObject(mapOf("format" to JsonPrimitive(1), "source_context" to JsonPrimitive(value.sourceContext),
            "plain_bytes" to JsonPrimitive(value.plainBytes), "cipher_budget" to JsonPrimitive(value.cipherBudget),
            "root_key" to (value.rootKey?.let { JsonPrimitive(it) } ?: JsonNull), "phase" to JsonPrimitive(value.phase),
            "snapshot" to (value.snapshot ?: JsonNull)))
        private fun frame(value: JsonObject) = ByteArrayOutputStream().also {
            TelefonRahmen.schreiben(it, value, DeviceTransferProtection.MAX_CLEAR_BYTES - 4)
        }.toByteArray()
        private fun parse(bytes: ByteArray) = ByteArrayInputStream(bytes).use { input ->
            TelefonRahmen.lesen(input, DeviceTransferProtection.MAX_CLEAR_BYTES - 4).also { if (input.read() != -1) fail("photo_jobs_trailing_metadata") }
        }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
