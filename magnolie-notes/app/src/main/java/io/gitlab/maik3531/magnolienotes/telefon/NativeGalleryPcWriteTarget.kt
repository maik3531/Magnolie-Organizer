package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.system.Os
import android.system.OsConstants
import kotlinx.serialization.json.*
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

/** Closed typed possession of an exact nontruncating writable original FD.
 * No raw FD, stream, write/truncate method or restart factory is exported.
 * First mutation still requires a separate durable write-start transition. */
internal class NativeGalleryPcWriteTarget internal constructor(private val descriptor: ParcelFileDescriptor,
    private val stage: NativeGalleryPcStage, private val grant: NativeGalleryPcWriteGrant,
    private val index: PhotoSourceJobIndex, private val record: GalleryPcPreWriteRecord,
    private val lane: Any, private val cancellation: CancellationSignal) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val startAttempted = AtomicBoolean(false)
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
        if (witness(descriptor) != record.body.getValue("descriptor")) fail()
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
    override fun close() { if (closed.compareAndSet(false, true)) descriptor.close() }
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
