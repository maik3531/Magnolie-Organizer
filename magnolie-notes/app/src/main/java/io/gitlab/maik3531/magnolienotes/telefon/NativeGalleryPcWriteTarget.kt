package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.system.Os
import android.system.OsConstants
import kotlinx.serialization.json.*
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

/** Raw local bytes only, NOT provider publication, durable postwrite/history
 * completion, Saved or a capability to resume a stored write_started record. */
internal data class NativeGalleryPcWrittenBytesObservation(val bytes: Long, val sha256: String,
    val descriptor: JsonObject, val media: NativeIncomingMediaObservation) {
    val grantsWriteAuthority: Boolean get() = false
    val isSavedReceipt: Boolean get() = false
}

/** Closed typed possession of an exact nontruncating writable original FD.
 * No raw FD, stream, arbitrary-reader writer or restart factory is exported. */
internal class NativeGalleryPcWriteTarget internal constructor(private val descriptor: ParcelFileDescriptor,
    private val stage: NativeGalleryPcStage, private val grant: NativeGalleryPcWriteGrant,
    private val index: PhotoSourceJobIndex, private val record: GalleryPcPreWriteRecord,
    private val lane: Any, private val cancellation: CancellationSignal) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val startAttempted = AtomicBoolean(false)
    private val copyAttempted = AtomicBoolean(false)
    @Volatile private var ownMutation = false
    @Volatile private var copyFailed = false
    @Volatile private var consumedHere = false
    private data class Records(val current: GalleryPcPreWriteRecord, val committing: GalleryPcPreWriteRecord? = null)
    @Volatile private var records = Records(record)
    init {
        if (record.state != "before_write") fail()
        requireCurrent()
        Os.lseek(descriptor.fileDescriptor, 0, OsConstants.SEEK_SET)
        val expected = record.stage.plan.predecessor.body
        val digest = MessageDigest.getInstance("SHA-256"); var size = 0L
        ParcelFileDescriptor.AutoCloseInputStream(ParcelFileDescriptor.dup(descriptor.fileDescriptor)).use { input ->
            val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
            try {
                while (size < expected.long("size")) {
                    requireCurrent()
                    val count = input.read(buffer, 0, minOf(buffer.size.toLong(), expected.long("size") - size).toInt())
                    requireCurrent()
                    if (count <= 0) fail()
                    digest.update(buffer, 0, count); size += count
                }
                if (input.read() != -1 || NativeHex.lower(digest.digest()) != expected.string("sha256")) fail()
            } finally { buffer.fill(0) }
        }
        NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, size, stage.kind, stage.mimeType, ensureNative = ::requireCurrent)
        requireCurrent()
    }
    internal fun requireCurrent() {
        if (closed.get() || !NativeGalleryMediaIoLane.isOwnedBy(lane)) fail()
        cancellation.throwIfCanceled()
        if (consumedHere) grant.requireCurrent() else grant.requireUnused()
        grant.request.admission.requireIndex(index); stage.requireCurrent()
        val before = records; val actual = index.pcBeforeWrite(record.id)?.body; val after = records
        if (!record.stage.sealed || record.stage.body != stage.record.body ||
            record.stage.plan.predecessor.body != grant.request.admission.publication.body ||
            listOfNotNull(before.current, before.committing, after.current, after.committing).none { it.body == actual }) fail()
        val flags = Os.fcntlInt(descriptor.fileDescriptor, OsConstants.F_GETFL, 0)
        if (flags and OsConstants.O_ACCMODE != OsConstants.O_RDWR) fail()
        val actualDescriptor = witness(descriptor); val original = record.body.getValue("descriptor").jsonObject
        if (!ownMutation) {
            if (actualDescriptor != original) fail()
        } else {
            // Only the one admitted local copy may change size/timestamps.
            // Never relax native identity, mode, links or ownership.
            if (!copyAttempted.get() || records.current.state != "write_started" ||
                listOf("device", "inode", "mode", "links", "uid", "gid").any { actualDescriptor[it] != original[it] } ||
                actualDescriptor.long("size") !in 0..maxOf(original.long("size"), stage.manifest.totalBytes)) fail()
        }
        cancellation.throwIfCanceled()
    }
    internal fun startWrite(): GalleryPcPreWriteRecord {
        requireCurrent()
        if (!startAttempted.compareAndSet(false, true) || records.current.state != "before_write") fail()
        grant.consume(); consumedHere = true
        val next = record.startWrite(); records = Records(record, next)
        index.startPcWrite(this, record, next)
        records = Records(next); requireCurrent(); return next
    }
    internal fun requireLocalStartOwner(actual: PhotoSourceJobIndex, expected: GalleryPcPreWriteRecord, next: GalleryPcPreWriteRecord) {
        val snapshot = records
        if (closed.get() || actual !== index || !NativeGalleryMediaIoLane.isOwnedBy(lane) || !startAttempted.get() || !consumedHere ||
            snapshot.current !== record || snapshot.committing !== next || expected !== record) fail()
        cancellation.throwIfCanceled(); grant.request.admission.requireLocal()
    }
    internal fun requireStartOwner(actual: PhotoSourceJobIndex, expected: GalleryPcPreWriteRecord, next: GalleryPcPreWriteRecord) {
        requireLocalStartOwner(actual, expected, next); requireCurrent(); requireLocalStartOwner(actual, expected, next)
    }
    private fun verifyBytes(bytes: Long, sha256: String): NativeIncomingMediaObservation {
        requireCurrent(); val before = witness(descriptor)
        if (before.long("size") != bytes) fail()
        Os.lseek(descriptor.fileDescriptor, 0, OsConstants.SEEK_SET)
        val hash = MessageDigest.getInstance("SHA-256"); var size = 0L
        ParcelFileDescriptor.AutoCloseInputStream(ParcelFileDescriptor.dup(descriptor.fileDescriptor)).use { input ->
            val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
            try {
                while (size < bytes) {
                    requireCurrent(); val count = input.read(buffer, 0, minOf(buffer.size.toLong(), bytes - size).toInt()); requireCurrent()
                    if (count <= 0) fail()
                    hash.update(buffer, 0, count); size += count
                }
                if (input.read() != -1 || NativeHex.lower(hash.digest()) != sha256) fail()
            } finally { buffer.fill(0) }
        }
        val observation = NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, bytes, stage.kind, stage.mimeType,
            ensureNative = ::requireCurrent)
        requireCurrent(); if (witness(descriptor) != before) fail()
        return observation
    }
    internal fun copyVerifiedBytes(archive: NativeGalleryTrashArchive, boundary: (String) -> Unit): NativeGalleryPcWrittenBytesObservation {
        requireCurrent()
        if (!copyAttempted.compareAndSet(false, true) || records.current.state != "write_started" || !consumedHere) fail()
        fun checkArchive() {
            requireCurrent()
            val origin = archive.verifiedOrigin(grant.request.entry, grant.request.admission.archiveBook)
            if (origin["publication"] != record.stage.plan.predecessor.body || origin["book_version"] != record.stage.plan.body["book_version"])
                fail()
            requireCurrent()
        }
        try {
            checkArchive(); stage.verifyRaw()
            verifyBytes(record.stage.plan.predecessor.body.long("size"), record.stage.plan.predecessor.body.string("sha256"))
            stage.verifyRaw(); checkArchive(); requireCurrent()
            val expected = stage.manifest.files.single(); var copied = 0L
            val hash = MessageDigest.getInstance("SHA-256")
            ownMutation = true
            Os.lseek(descriptor.fileDescriptor, 0, OsConstants.SEEK_SET)
            ParcelFileDescriptor.AutoCloseOutputStream(ParcelFileDescriptor.dup(descriptor.fileDescriptor)).use { output ->
                stage.input().use { input ->
                    val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
                    try {
                        while (copied < expected.size) {
                            requireCurrent()
                            val count = input.read(buffer, 0, minOf(buffer.size.toLong(), expected.size - copied).toInt())
                            requireCurrent(); if (count <= 0) fail()
                            output.write(buffer, 0, count); copied += count; hash.update(buffer, 0, count)
                            boundary("pc-replacement-bytes-written"); requireCurrent()
                        }
                        if (input.read() != -1 || NativeHex.lower(hash.digest()) != expected.sha256) fail()
                        requireCurrent(); output.flush()
                        output.channel.truncate(expected.size); output.channel.force(true); requireCurrent()
                        boundary("pc-replacement-bytes-forced"); requireCurrent()
                    } finally { buffer.fill(0) }
                }
            }
            val media = verifyBytes(expected.size, expected.sha256)
            stage.verifyRaw(); checkArchive(); requireCurrent()
            val result = NativeGalleryPcWrittenBytesObservation(expected.size, expected.sha256, witness(descriptor), media)
            // Provider row metadata may update only asynchronously on this real
            // close. Return no publication/history/Saved proof from it.
            close(); return result
        } catch (error: Throwable) { copyFailed = true; throw error }
    }
    override fun close() {
        if (closed.compareAndSet(false, true)) {
            try {
                if (copyFailed) descriptor.closeWithError("PC replacement interrupted; original archive and write fence retained")
            } finally { descriptor.close() }
        }
    }
    companion object {
        internal fun witness(descriptor: ParcelFileDescriptor): JsonObject {
            val stat = Os.fstat(descriptor.fileDescriptor)
            return buildJsonObject {
                put("device", stat.st_dev); put("inode", stat.st_ino); put("mode", stat.st_mode); put("links", stat.st_nlink)
                put("uid", stat.st_uid); put("gid", stat.st_gid); put("size", stat.st_size)
                put("mtime_s", stat.st_mtim.tv_sec); put("mtime_ns", stat.st_mtim.tv_nsec)
                put("ctime_s", stat.st_ctim.tv_sec); put("ctime_ns", stat.st_ctim.tv_nsec)
            }
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_pc_write_target_changed")
    }
}
