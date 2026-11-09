package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import kotlinx.serialization.json.*
import java.util.concurrent.atomic.AtomicBoolean
import java.security.MessageDigest

/** Current actual incoming control/policy/intent ownership, not a historical
 * journal record or local archive restoration. Runtime must serialize this
 * lane against source/receiver work. No production factory enables it yet. */
internal class NativeGalleryIncomingOwner private constructor(private val session: NativeFileControlSession,
    private val index: PhotoSourceJobIndex, private val book: NativeGalleryReceiveBookPermit,
    private val peer: () -> NativeFileControlPeer?, private val incomingIntent: () -> Any?,
    internal val manifest: DeviceFileManifest, internal val kind: GalleryMediaType,
    references: Map<String, GalleryPhoneMediaReference>, pcOrigins: Map<String, GalleryPcMediaOrigin>,
    expectedControl: NativeFileOperationBinding?) : AutoCloseable {
    private val token = incomingIntent() as? MediaSyncTransport.IntentToken ?: fail()
    internal val photosOnly: Boolean get() = token.photosOnly
    private val originalPeer = peer()?.takeIf { it.allowed && it.pairingEpoch != null } ?: fail()
    internal val pairingEpoch = originalPeer.pairingEpoch!!
    private val originalControl = session.operationBinding(manifest.fingerprint) ?: fail()
    internal val binding = originalControl.binding
    private val policy = index.galleryPolicy()
    private val issued = DeviceFileControl.monotonicMs()
    private var last = issued
    private val ended = AtomicBoolean(false)
    internal val scope: GalleryIncomingScope
    init {
        if (expectedControl != null && originalControl != expectedControl) fail()
        requireCurrent()
        scope = GalleryIncomingScope.capture(manifest, kind, token.collectionMode, binding.senderIdentitySha256,
            references, pcOrigins, index::knownPhoneMedia)
        requireCurrent()
    }

    /** Safe inside index guards: no transport/Werk/session/index call. */
    @Synchronized internal fun requireLocal() {
        try {
            val now = DeviceFileControl.monotonicMs()
            if (ended.get() || now < last || now - issued >= DeviceFileControl.MAX_TTL_MS ||
                incomingIntent() !== token || !token.requestedIncoming(kind)) fail()
            book.requireCurrent(); last = now
        } catch (error: Exception) { ended.set(true); throw error }
    }

    /** Call only outside any index/MediaStore/provider monitor. */
    internal fun requireCurrent() {
        try {
            requireLocal()
            val current = peer() ?: fail()
            if (!current.allowed || kind == GalleryMediaType.VIDEO && !current.videoSupported ||
                current.owner !== originalPeer.owner || current.peerId != originalPeer.peerId ||
                current.identitySha256 != originalPeer.identitySha256 || current.pairingEpoch != pairingEpoch ||
                session.operationBinding(manifest.fingerprint) != originalControl || index.galleryPolicy() != policy || policy.repairPending ||
                policy.policy?.let { it.receiverId == current.peerId && it.receiverIdentitySha256 == current.identitySha256 &&
                    it.pairingEpoch == pairingEpoch && it.receiving?.enabled(kind) == true } != true ||
                binding.senderId != manifest.senderId || binding.receiverId != manifest.receiverId ||
                binding.senderId != current.peerId || binding.senderIdentitySha256 != current.identitySha256) fail()
        } catch (error: Exception) { ended.set(true); throw error }
    }
    override fun close() { ended.set(true) }
    internal fun requireChannel(channel: TelefonSecureChannel) {
        requireCurrent()
        if (originalPeer.owner !== channel) { ended.set(true); fail() }
    }
    companion object {
        internal fun capture(session: NativeFileControlSession, index: PhotoSourceJobIndex, book: NativeGalleryReceiveBookPermit,
            currentPeer: () -> NativeFileControlPeer?, incomingIntent: () -> Any?, manifest: DeviceFileManifest,
            kind: GalleryMediaType, references: Map<String, GalleryPhoneMediaReference> = emptyMap(),
            pcOrigins: Map<String, GalleryPcMediaOrigin> = emptyMap(), expectedControl: NativeFileOperationBinding? = null): NativeGalleryIncomingOwner {
            if (Build.VERSION.SDK_INT < 30 || Looper.myLooper() == Looper.getMainLooper()) fail()
            return NativeGalleryIncomingOwner(session, index, book, currentPeer, incomingIntent, manifest, kind, references.toMap(), pcOrigins.toMap(), expectedControl)
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_incoming_current_owner_required")
    }
}

/** Actual new app-owned PENDING MediaStore rows only. No publication,
 * deletion, permission request or Saved receipt. An uncertain insertion is
 * retained, never retried by name, overwritten or silently adopted. */
internal class NativeGalleryIncomingRows(context: Context, private val index: PhotoSourceJobIndex) {
    private val app = context.applicationContext
    private val resolver = app.contentResolver
    private class VerifiedRead(val owner: NativeGalleryPublishedInspection, val observation: NativeIncomingMediaObservation,
        val recovery: NativeGalleryPublishedReadback)
    private val verifiedRead = ThreadLocal<VerifiedRead?>()
    private class ArchiveTarget(val permit: NativeGalleryTrashBookPermit, private val supplied: NativeGalleryTrashArchive? = null,
        private val protection: DeviceTransferProtection? = null, val writeAdmission: NativeGalleryPcWriteAdmission? = null) {
        var archive: NativeGalleryTrashArchive? = supplied
            private set
        val ownsArchive: Boolean get() = supplied == null
        var result: NativeGalleryArchiveEntry? = null
        var writeRequest: NativeGalleryPcWriteRequest? = null
        fun open(app: Context): NativeGalleryTrashArchive = archive ?: NativeGalleryTrashArchive.openForApplication(app,
            protection ?: DeviceFileControl.fail("gallery_archive_published_pc_owner_required")).also { archive = it }
    }
    private class VerifiedArchive(val owner: NativeGalleryPublishedInspection, val target: ArchiveTarget)
    private val verifiedArchive = ThreadLocal<VerifiedArchive?>()

    internal fun prepare(owner: NativeGalleryIncomingOwner, fileId: String, mimeType: String): GalleryIncomingPublication {
        if (Looper.myLooper() == Looper.getMainLooper() || Build.VERSION.SDK_INT < 30)
            fail("gallery_incoming_io_android30_required")
        owner.requireCurrent()
        val planned = GalleryIncomingPublication.plan(owner.binding, owner.manifest, fileId, owner.pairingEpoch, owner.kind, mimeType, owner.scope)
        val saved = index.reserveIncomingPublication(planned, owner::requireLocal)
        owner.requireCurrent()
        if (saved.state == "inserted") {
            if (observe(owner, Uri.parse(saved.row!!.string("uri")), mimeType) != saved.row)
                fail("gallery_incoming_original_row_changed")
            return saved
        }
        if (saved.state != "planned") fail("gallery_incoming_insertion_uncertain")
        val volume = MediaStore.VOLUME_EXTERNAL_PRIMARY
        if (volume !in MediaStore.getExternalVolumeNames(app)) fail("gallery_incoming_volume_missing")
        val namespace = MediaStore.getVersion(app, volume)
        if (namespace.isNullOrEmpty() || namespace.length > 1024 || namespace.any { it.code < 32 || it.code == 127 })
            fail("gallery_incoming_namespace_invalid")
        val inserting = index.beginIncomingInsertion(saved, owner::requireLocal)
        owner.requireCurrent()
        if (volume !in MediaStore.getExternalVolumeNames(app) || MediaStore.getVersion(app, volume) != namespace)
            fail("gallery_incoming_namespace_changed")
        val uri = resolver.insert(owner.kind.collection(volume, true), ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, planned.body.string("name"))
            put(MediaStore.MediaColumns.MIME_TYPE, mimeType)
            put(MediaStore.MediaColumns.RELATIVE_PATH, path(owner.kind))
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }) ?: fail("gallery_incoming_insert_missing")
        owner.requireCurrent()
        val row = observe(owner, uri, mimeType)
        if (row.string("namespace") != namespace) fail("gallery_incoming_namespace_changed")
        val recorded = index.recordIncomingRow(inserting, row, owner::requireLocal)
        owner.requireCurrent()
        if (observe(owner, uri, mimeType) != row) fail("gallery_incoming_original_row_changed")
        return recorded
    }

    /** Copy original bytes once into the exact new empty pending row. A durable
     * copying head forbids reopening for write after ANY interruption. Complete
     * interrupted copies can only be reverified read-only; partial ones hold.
     * This is not MIME/content admission, row publication or Saved output. */
    internal fun copyAndVerify(owner: NativeGalleryIncomingOwner, selected: GalleryIncomingPublication,
        readChunk: (Int) -> ByteArray, cancellation: CancellationSignal = CancellationSignal()): GalleryIncomingPublication {
        if (Looper.myLooper() == Looper.getMainLooper()) fail("gallery_incoming_io_android30_required")
        fun current() { cancellation.throwIfCanceled(); owner.requireCurrent() }
        current()
        val body = selected.body
        val origin = body["origin"] as? JsonObject ?: fail("gallery_incoming_original_changed")
        val planned = GalleryIncomingPublication.plan(owner.binding, owner.manifest, origin.string("file_id"), owner.pairingEpoch,
            owner.kind, body.string("mime_type"), owner.scope)
        if (planned.body.filterKeys { it !in setOf("state", "row") } != body.filterKeys { it !in setOf("state", "row") } ||
            index.incomingPublication(selected.id)?.body != body || selected.state !in setOf("inserted", "copying", "copy_verified"))
            fail("gallery_incoming_original_changed")
        val uri = Uri.parse(selected.row!!.string("uri")); val size = body.long("size"); val hash = body.string("sha256")
        fun sameMember(row: JsonObject) = row.filterKeys { it != "revision" } == selected.row!!.filterKeys { it != "revision" } &&
            row.string("revision").toLong() >= selected.row!!.string("revision").toLong()
        val initial = observe(owner, uri, body.string("mime_type"), if (selected.state == "inserted") 0L..0L else 0L..size)
        if (!sameMember(initial)) fail("gallery_incoming_original_row_changed")
        val copying = if (selected.state == "inserted") index.beginIncomingCopy(selected, owner::requireLocal) else selected
        current()
        if (selected.state == "inserted") {
            if (observe(owner, uri, body.string("mime_type")) != initial) fail("gallery_incoming_original_row_changed")
            val descriptor = resolver.openFileDescriptor(uri, "w", cancellation) ?: fail("gallery_incoming_output_missing")
            ParcelFileDescriptor.AutoCloseOutputStream(descriptor).use { output ->
                current()
                if (descriptor.statSize != 0L) fail("gallery_incoming_empty_row_required")
                val digest = MessageDigest.getInstance("SHA-256")
                val chunks = ((size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
                for (chunk in 0 until chunks) {
                    current(); val bytes = readChunk(chunk)
                    try {
                        current()
                        val wanted = minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), size - chunk.toLong() * DeviceFileManifest.CHUNK_BYTES).toInt()
                        if (bytes.size != wanted) fail("gallery_incoming_chunk_size_changed")
                        output.write(bytes); digest.update(bytes); current()
                    } finally { bytes.fill(0) }
                }
                if (digest.digest().joinToString("") { "%02x".format(it) } != hash) fail("gallery_incoming_content_changed")
                output.flush(); descriptor.fileDescriptor.sync(); current()
            }
        }
        val copied = observe(owner, uri, body.string("mime_type"), size..size)
        if (!sameMember(copied)) fail("gallery_incoming_original_row_changed")
        current(); verifyOriginalBytes(owner, uri, size, hash, cancellation)
        if (observe(owner, uri, body.string("mime_type"), size..size) != copied) fail("gallery_incoming_original_row_changed")
        current()
        if (selected.state == "copy_verified") {
            if (copied != selected.row) fail("gallery_incoming_original_row_changed")
            return selected // Fresh readback, never a cached completion assertion.
        }
        val verified = index.recordIncomingVerifiedCopy(copying, copied, owner::requireLocal)
        current(); return verified
    }

    private fun verifyOriginalBytes(owner: NativeGalleryIncomingOwner, uri: Uri, size: Long, hash: String,
        cancellation: CancellationSignal) = verifyOriginalBytes(uri, size, hash, cancellation, owner::requireCurrent)

    private fun verifyOriginalBytes(uri: Uri, size: Long, hash: String, cancellation: CancellationSignal, ensureCurrent: () -> Unit) {
        fun current() { cancellation.throwIfCanceled(); ensureCurrent() }
        current(); val original = MediaStore.setRequireOriginal(uri)
        val stream = if (Build.VERSION.SDK_INT >= 31) {
            val asset = resolver.openTypedAssetFileDescriptor(original, "*/*", Bundle().apply {
                putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true)
            }, cancellation) ?: fail("gallery_incoming_readback_missing")
            try { asset.createInputStream() } catch (error: Exception) { asset.close(); throw error }
        } else ParcelFileDescriptor.AutoCloseInputStream(resolver.openFileDescriptor(original, "r", cancellation)
            ?: fail("gallery_incoming_readback_missing"))
        stream.use { input ->
            val digest = MessageDigest.getInstance("SHA-256"); var count = 0L
            val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
            try {
                while (true) {
                    current(); val read = input.read(buffer); current()
                    if (read == -1) break
                    if (read <= 0 || count + read > size) fail("gallery_incoming_content_changed")
                    count += read; digest.update(buffer, 0, read)
                }
                if (count != size || digest.digest().joinToString("") { "%02x".format(it) } != hash) fail("gallery_incoming_content_changed")
            } finally { buffer.fill(0) }
        }
        current()
    }

    /** Native new-row publication only. No remote Saved output or source/cache
     * retirement is implied. Lost update replies leave a durable publishing
     * head; retries verify the exact visible row without another update/copy. */
    internal fun publish(owner: NativeGalleryIncomingOwner, selected: GalleryIncomingPublication,
        cancellation: CancellationSignal = CancellationSignal()): GalleryIncomingPublication {
        if (Looper.myLooper() == Looper.getMainLooper()) fail("gallery_incoming_io_android30_required")
        fun current() { cancellation.throwIfCanceled(); owner.requireCurrent() }
        current()
        val body = selected.body; val savedRow = selected.row ?: fail("gallery_incoming_verified_copy_required")
        val fileId = (body["origin"] as? JsonObject)?.string("file_id") ?: fail("gallery_incoming_original_changed")
        val expected = GalleryIncomingPublication.plan(owner.binding, owner.manifest, fileId, owner.pairingEpoch, owner.kind, body.string("mime_type"), owner.scope)
        if (selected.state !in setOf("copy_verified", "publishing", "published") || index.incomingPublication(selected.id)?.body != body ||
            expected.body.filterKeys { it !in setOf("state", "row") } != body.filterKeys { it !in setOf("state", "row") })
            fail("gallery_incoming_verified_copy_required")
        val uri = Uri.parse(savedRow.string("uri")); val size = body.long("size"); val mime = body.string("mime_type")
        fun sameMember(row: JsonObject) = savedRow.filterKeys { it != "revision" } == row.filterKeys { it != "revision" } &&
            row.string("revision").toLong() >= savedRow.string("revision").toLong()
        fun inspect(row: NativeRow) {
            current()
            verifyOriginalBytes(owner, uri, size, body.string("sha256"), cancellation)
            val original = MediaStore.setRequireOriginal(uri)
            fun probe(descriptor: ParcelFileDescriptor) {
                NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, size, owner.kind, mime, owner.photosOnly, ::current)
            }
            if (Build.VERSION.SDK_INT >= 31) {
                val asset = resolver.openTypedAssetFileDescriptor(original, "*/*", Bundle().apply {
                    putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true)
                }, cancellation) ?: fail("gallery_incoming_readback_missing")
                asset.use {
                    if (it.startOffset != 0L) fail("gallery_incoming_original_offset_changed")
                    probe(it.parcelFileDescriptor)
                }
            } else {
                val descriptor = resolver.openFileDescriptor(original, "r", cancellation) ?: fail("gallery_incoming_readback_missing")
                descriptor.use(::probe)
            }
            // Inspecting headers does not replace original-byte verification.
            verifyOriginalBytes(owner, uri, size, body.string("sha256"), cancellation)
            if (observeRow(owner, uri, mime, size..size, null) != row) fail("gallery_incoming_original_row_changed")
        }
        val before = observeRow(owner, uri, mime, size..size, null)
        if (!sameMember(before.witness) || selected.state == "copy_verified" && (before.pending != 1L || before.witness != savedRow) ||
            selected.state == "published" && (before.pending != 0L || before.witness != savedRow)) fail("gallery_incoming_original_row_changed")
        inspect(before)
        if (selected.state == "published") return selected // Revalidated history, never automatic Saved output.
        val publishing = if (selected.state == "copy_verified") index.beginIncomingPublishing(selected, owner::requireLocal) else selected
        current()
        if (before.pending == 1L) {
            if (before.witness != savedRow || observeRow(owner, uri, mime, size..size, 1) != before)
                fail("gallery_incoming_original_row_changed")
            val parts = savedRow.string("member").split(':')
            val count = resolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                "_id = ? AND date_added = ? AND generation_added = ? AND generation_modified = ? AND owner_package_name = ? AND relative_path = ? AND mime_type = ? AND _display_name = ? AND _size = ? AND is_pending = 1 AND is_trashed = 0",
                arrayOf(parts[0], parts[1], parts[2], savedRow.string("revision"), app.packageName, savedRow.string("path"),
                    mime, savedRow.string("name"), size.toString()))
            if (count != 1) fail("gallery_incoming_publish_not_proven")
        }
        current()
        val visible = observeRow(owner, uri, mime, size..size, 0)
        if (!sameMember(visible.witness) || visible.witness.string("revision").toLong() <= savedRow.string("revision").toLong())
            fail("gallery_incoming_publish_not_proven")
        inspect(visible)
        val published = index.recordIncomingPublished(publishing, visible.witness, owner::requireLocal)
        current()
        if (observeRow(owner, uri, mime, size..size, 0) != visible) fail("gallery_incoming_original_row_changed")
        return published
    }

    /** Read-only native verification of an existing published row under fresh
     * current rights. No journal mutation or receipt is generated. Lane ownership
     * drains real provider I/O even when the caller cancels/closes its owner. */
    internal fun inspectPublished(owner: NativeGalleryPublishedInspection,
        cancellation: CancellationSignal = CancellationSignal()): NativeIncomingMediaObservation = inspectPublishedOwned(owner, cancellation, null)

    internal fun recoverPublished(recovery: NativeGalleryPublishedReadback, cancellation: CancellationSignal): JsonObject {
        inspectPublishedOwned(recovery.owner, cancellation, recovery)
        return recovery.actualOutput() ?: fail("gallery_published_native_readback_required")
    }

    /** Actual app-owned PC row copy only. It does not publish, replace, trash,
     * delete or manufacture an outgoing phone GalleryPhotoSourceLease. */
    internal fun archivePublishedPc(owner: NativeGalleryPublishedInspection, archive: NativeGalleryTrashArchive,
        permit: NativeGalleryTrashBookPermit, cancellation: CancellationSignal = CancellationSignal()): NativeGalleryArchiveEntry =
        archivePublishedPc(owner, ArchiveTarget(permit, supplied = archive), cancellation)

    internal fun archivePublishedPcToApplication(owner: NativeGalleryPublishedInspection, protection: DeviceTransferProtection,
        permit: NativeGalleryTrashBookPermit, cancellation: CancellationSignal): NativeGalleryArchiveEntry =
        archivePublishedPc(owner, ArchiveTarget(permit, protection = protection), cancellation)

    /** Only prepares an OS request after the real archive/row proof; no writer,
     * replacement history transition or old phone READ owner is created. */
    internal fun preparePublishedPcWrite(admission: NativeGalleryPcWriteAdmission, archive: NativeGalleryTrashArchive,
        cancellation: CancellationSignal = CancellationSignal()): NativeGalleryPcWriteRequest {
        val target = ArchiveTarget(admission.archiveBook, supplied = archive, writeAdmission = admission)
        try {
            admission.bindCancellation(cancellation)
            archivePublishedPc(admission.inspection(), target, cancellation)
            return target.writeRequest ?: fail("gallery_pc_write_os_owner_required")
        } catch (error: Throwable) { target.writeRequest?.close(); admission.close(); throw error }
    }

    private fun archivePublishedPc(owner: NativeGalleryPublishedInspection, target: ArchiveTarget,
        cancellation: CancellationSignal): NativeGalleryArchiveEntry {
        try {
            owner.requireArchiveBook(target.permit)
            if (owner.selected.pcOrigin == null) fail("gallery_archive_published_pc_owner_required")
            inspectPublishedOwned(owner, cancellation, null, target)
            return target.result ?: fail("gallery_archive_published_pc_owner_required")
        } catch (error: Throwable) { owner.close(); throw error }
    }

    internal fun requireVerifiedArchive(archive: NativeGalleryTrashArchive, owner: NativeGalleryPublishedInspection,
        permit: NativeGalleryTrashBookPermit) {
        val actual = verifiedArchive.get()
        if (actual == null || actual.owner !== owner || actual.target.archive !== archive || actual.target.permit !== permit)
            fail("gallery_archive_published_pc_owner_required")
        owner.requireArchiveBook(permit)
    }

    private class VerifiedPcBeforeWrite(val stage: NativeGalleryPcStage, val grant: NativeGalleryPcWriteGrant,
        val record: GalleryPcPreWriteRecord, val lane: Any, val cancellation: CancellationSignal)
    private val verifiedPcBeforeWrite = ThreadLocal<VerifiedPcBeforeWrite?>()
    internal fun preparePcWriteTarget(stage: NativeGalleryPcStage, grant: NativeGalleryPcWriteGrant,
        archive: NativeGalleryTrashArchive, lane: Any, cancellation: CancellationSignal,
        deadline: NativeGalleryPcReplacementDeadline): NativeGalleryPcWriteTarget {
        if (Looper.myLooper() == Looper.getMainLooper() || Build.VERSION.SDK_INT < 30 || !NativeGalleryMediaIoLane.isOwnedBy(lane))
            fail("gallery_pc_before_write_native_proof_required")
        val admission = grant.request.admission
        fun current() { cancellation.throwIfCanceled(); admission.requireIndex(index); grant.requireUnused(); stage.requireCurrent() }
        current()
        val record = index.pcBeforeWrite(stage.record.id) ?: fail("gallery_pc_before_write_native_proof_required")
        if (record.state != "before_write" || record.stage.body != stage.record.body || record.stage.plan.predecessor.body != admission.publication.body)
            fail("gallery_pc_before_write_original_operation_required")
        val publication = admission.publication; val row = publication.row!!; val uri = grant.request.uri
        fun checkRow() {
            if (uri.toString() != row.string("uri") || observeRow(stage.kind, ::current, uri, stage.mimeType,
                    publication.body.long("size")..publication.body.long("size"), 0).witness != row) fail("gallery_incoming_original_row_changed")
        }
        fun checkArchive() {
            current()
            val origin = archive.verifiedOrigin(grant.request.entry, admission.archiveBook)
            if (origin["publication"] != publication.body || origin["book_version"] != record.stage.plan.body["book_version"])
                fail("gallery_pc_before_write_archive_changed")
            current()
        }
        checkRow(); checkArchive(); stage.verifyRaw(); current()
        // rw is deliberately NONTRUNCATING. Never w or rwt on the old original.
        val descriptor = resolver.openFileDescriptor(MediaStore.setRequireOriginal(uri), "rw", cancellation)
            ?: fail("gallery_pc_write_target_missing")
        var target: NativeGalleryPcWriteTarget? = null
        try {
            target = NativeGalleryPcWriteTarget(descriptor, stage, grant, index, record, lane, cancellation, deadline)
            checkRow(); checkArchive(); target.requireCurrent(); return target
        } catch (error: Throwable) { if (target == null) descriptor.close() else target.close(); throw error }
    }
    /** Only the actual original-FD verification below can publish this proof.
     * Local-only checks are safe inside the protected index transaction. */
    internal fun requireVerifiedPcBeforeWrite(stage: NativeGalleryPcStage, grant: NativeGalleryPcWriteGrant,
        record: GalleryPcPreWriteRecord) {
        val actual = verifiedPcBeforeWrite.get()
        if (actual == null || actual.stage !== stage || actual.grant !== grant || actual.record !== record ||
            !NativeGalleryMediaIoLane.isOwnedBy(actual.lane)) fail("gallery_pc_before_write_native_proof_required")
        actual.cancellation.throwIfCanceled(); grant.request.admission.requireLocal()
    }

    /** Read-only preflight. A future writable FD must itself be freshly checked
     * against this descriptor witness; this record cannot authorize that open. */
    internal fun preparePcBeforeWrite(stage: NativeGalleryPcStage, grant: NativeGalleryPcWriteGrant,
        archive: NativeGalleryTrashArchive, lane: Any, cancellation: CancellationSignal): GalleryPcPreWriteRecord {
        if (Looper.myLooper() == Looper.getMainLooper() || Build.VERSION.SDK_INT < 30 || !NativeGalleryMediaIoLane.isOwnedBy(lane))
            fail("gallery_pc_before_write_native_proof_required")
        val admission = grant.request.admission
        fun current() {
            cancellation.throwIfCanceled(); admission.requireIndex(index); grant.requireUnused(); stage.requireCurrent()
        }
        current()
        val staged = stage.record
        if (!staged.sealed || staged.plan.predecessor.body != admission.publication.body ||
            index.pcBeforeWrite(staged.id) != null) fail("gallery_pc_before_write_original_operation_required")
        val publication = admission.publication; val row = publication.row!!
        val uri = Uri.parse(row.string("uri")); val size = publication.body.long("size"); val mime = publication.body.string("mime_type")
        val kind = GalleryMediaType.entries.single { it.uriSegment == publication.body.string("media_type") }
        fun checkRow() {
            if (observeRow(kind, ::current, uri, mime, size..size, 0).witness != row) fail("gallery_incoming_original_row_changed")
        }
        fun checkArchive() {
            current()
            val origin = archive.verifiedOrigin(grant.request.entry, admission.archiveBook)
            if (origin["publication"] != publication.body || origin["book_version"] != staged.plan.body["book_version"] ||
                staged.plan.body.getValue("archive").jsonObject != buildJsonObject {
                    put("id", grant.request.entry.id); put("version", grant.request.entry.version)
                    put("size", grant.request.entry.bytes); put("sha256", grant.request.entry.sha256)
                }) fail("gallery_pc_before_write_archive_changed")
            current()
        }
        fun descriptorWitness(descriptor: java.io.FileDescriptor): JsonObject {
            current(); val stat = android.system.Os.fstat(descriptor)
            if (!android.system.OsConstants.S_ISREG(stat.st_mode) || stat.st_size != size || stat.st_nlink != 1L)
                fail("gallery_pc_before_write_descriptor_changed")
            return buildJsonObject {
                put("device", stat.st_dev); put("inode", stat.st_ino); put("mode", stat.st_mode); put("links", stat.st_nlink)
                put("uid", stat.st_uid); put("gid", stat.st_gid); put("size", stat.st_size)
                put("mtime_s", stat.st_mtim.tv_sec); put("mtime_ns", stat.st_mtim.tv_nsec)
                put("ctime_s", stat.st_ctim.tv_sec); put("ctime_ns", stat.st_ctim.tv_nsec)
            }
        }
        fun verify(descriptor: ParcelFileDescriptor): GalleryPcPreWriteRecord {
            val before = descriptorWitness(descriptor.fileDescriptor)
            android.system.Os.lseek(descriptor.fileDescriptor, 0, android.system.OsConstants.SEEK_SET)
            val hash = MessageDigest.getInstance("SHA-256"); var bytes = 0L
            ParcelFileDescriptor.AutoCloseInputStream(ParcelFileDescriptor.dup(descriptor.fileDescriptor)).use { input ->
                val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
                try {
                    while (bytes < size) {
                        current(); val count = input.read(buffer, 0, minOf(buffer.size.toLong(), size - bytes).toInt()); current()
                        if (count <= 0) fail("gallery_pc_before_write_content_changed")
                        hash.update(buffer, 0, count); bytes += count
                    }
                    current()
                    if (input.read() != -1 || NativeHex.lower(hash.digest()) != publication.body.string("sha256"))
                        fail("gallery_pc_before_write_content_changed")
                } finally { buffer.fill(0) }
            }
            NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, size, kind, mime, ensureNative = ::current)
            checkArchive(); stage.verifyRaw(); checkRow()
            if (descriptorWitness(descriptor.fileDescriptor) != before) fail("gallery_pc_before_write_descriptor_changed")
            val record = GalleryPcPreWriteRecord.create(staged, before)
            if (verifiedPcBeforeWrite.get() != null) fail("gallery_pc_before_write_native_proof_required")
            verifiedPcBeforeWrite.set(VerifiedPcBeforeWrite(stage, grant, record, lane, cancellation))
            try {
                index.recordPcBeforeWrite(this, stage, grant, record)
                checkRow(); current()
                if (descriptorWitness(descriptor.fileDescriptor) != before) fail("gallery_pc_before_write_descriptor_changed")
                return record
            } finally { verifiedPcBeforeWrite.remove() }
        }
        checkRow(); checkArchive(); current()
        val original = MediaStore.setRequireOriginal(uri)
        if (Build.VERSION.SDK_INT >= 31) {
            val asset = resolver.openTypedAssetFileDescriptor(original, "*/*", Bundle().apply {
                putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true)
            }, cancellation) ?: fail("gallery_incoming_readback_missing")
            return asset.use {
                if (it.startOffset != 0L) fail("gallery_incoming_original_offset_changed")
                verify(it.parcelFileDescriptor)
            }
        }
        return (resolver.openFileDescriptor(original, "r", cancellation) ?: fail("gallery_incoming_readback_missing")).use(::verify)
    }

    internal fun readVerifiedPcArchiveChunks(archive: NativeGalleryTrashArchive, owner: NativeGalleryPublishedInspection,
        permit: NativeGalleryTrashBookPermit, cancellation: CancellationSignal, consume: (ByteArray) -> Unit) {
        fun current() { cancellation.throwIfCanceled(); requireVerifiedArchive(archive, owner, permit) }
        current(); val publication = owner.selected; val row = publication.row!!; val size = publication.body.long("size")
        val uri = Uri.parse(row.string("uri")); val mime = publication.body.string("mime_type")
        fun checkRow() {
            if (observeRow(owner.kind, ::current, uri, mime, size..size, 0).witness != row)
                fail("gallery_incoming_original_row_changed")
        }
        fun read(input: java.io.InputStream) {
            val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES); val digest = MessageDigest.getInstance("SHA-256"); var offset = 0L
            try {
                while (offset < size) {
                    val wanted = minOf(buffer.size.toLong(), size - offset).toInt(); var at = 0
                    while (at < wanted) {
                        current(); val count = input.read(buffer, at, wanted - at); current()
                        if (count <= 0) fail("gallery_archive_source_short_read")
                        at += count
                    }
                    val bytes = buffer.copyOf(wanted)
                    try { current(); digest.update(bytes); consume(bytes); current() }
                    finally { bytes.fill(0) }
                    offset += wanted
                }
                current()
                if (input.read() != -1 || digest.digest().joinToString("") { "%02x".format(it) } != publication.body.string("sha256"))
                    fail("gallery_archive_source_changed")
                current()
            } finally { buffer.fill(0) }
        }
        checkRow(); val original = MediaStore.setRequireOriginal(uri)
        if (Build.VERSION.SDK_INT >= 31) {
            val asset = resolver.openTypedAssetFileDescriptor(original, "*/*", Bundle().apply {
                putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true)
            }, cancellation) ?: fail("gallery_incoming_readback_missing")
            asset.use {
                if (it.startOffset != 0L) fail("gallery_incoming_original_offset_changed")
                it.createInputStream().use(::read)
            }
        } else ParcelFileDescriptor.AutoCloseInputStream(resolver.openFileDescriptor(original, "r", cancellation)
            ?: fail("gallery_incoming_readback_missing")).use(::read)
        checkRow(); current()
    }
    internal fun requireVerifiedRead(recovery: NativeGalleryPublishedReadback, owner: NativeGalleryPublishedInspection,
        observation: NativeIncomingMediaObservation) {
        val actual = verifiedRead.get()
        if (actual == null || actual.owner !== owner || actual.observation !== observation || actual.recovery !== recovery)
            fail("gallery_published_native_readback_required")
        owner.requireIndex(index)
    }

    private fun inspectPublishedOwned(owner: NativeGalleryPublishedInspection, cancellation: CancellationSignal,
        recovery: NativeGalleryPublishedReadback?, archive: ArchiveTarget? = null): NativeIncomingMediaObservation {
        if (Looper.myLooper() == Looper.getMainLooper() || Build.VERSION.SDK_INT < 30)
            fail("gallery_incoming_io_android30_required")
        owner.requireIndex(index); owner.consume()
        val lane = Any()
        if (!NativeGalleryMediaIoLane.acquire(lane)) { owner.close(); fail("gallery_incoming_worker_busy") }
        try {
            fun current() {
                cancellation.throwIfCanceled()
                if (archive == null) owner.requireCurrent() else owner.requireArchiveBook(archive.permit)
                recovery?.requireCurrent() // Original offer expiry also fences provider reads, not only proof output.
            }
            current()
            val selected = owner.selected; val body = selected.body; val row = selected.row!!
            val uri = Uri.parse(row.string("uri")); val size = body.long("size"); val mime = body.string("mime_type")
            fun checkRow() {
                if (observeRow(owner.kind, ::current, uri, mime, size..size, 0).witness != row)
                    fail("gallery_incoming_original_row_changed")
            }
            checkRow(); verifyOriginalBytes(uri, size, body.string("sha256"), cancellation, ::current)
            val original = MediaStore.setRequireOriginal(uri)
            fun probe(descriptor: ParcelFileDescriptor) = NativeIncomingMediaInspection.inspect(
                descriptor.fileDescriptor, size, owner.kind, mime, ensureNative = ::current)
            val observation = if (Build.VERSION.SDK_INT >= 31) {
                val asset = resolver.openTypedAssetFileDescriptor(original, "*/*", Bundle().apply {
                    putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true)
                }, cancellation) ?: fail("gallery_incoming_readback_missing")
                asset.use {
                    if (it.startOffset != 0L) fail("gallery_incoming_original_offset_changed")
                    probe(it.parcelFileDescriptor)
                }
            } else {
                val descriptor = resolver.openFileDescriptor(original, "r", cancellation) ?: fail("gallery_incoming_readback_missing")
                descriptor.use(::probe)
            }
            current(); verifyOriginalBytes(uri, size, body.string("sha256"), cancellation, ::current); checkRow(); current()
            if (recovery != null) {
                verifiedRead.set(VerifiedRead(owner, observation, recovery))
                try { recovery.sendVerified(this, owner, observation, cancellation, ::checkRow) }
                finally { verifiedRead.remove() }
            }
            if (archive != null) {
                val target = archive.open(app); current()
                verifiedArchive.set(VerifiedArchive(owner, archive))
                try {
                    archive.result = target.archivePublishedPc(this, owner, archive.permit, cancellation)
                    checkRow(); current()
                    archive.writeAdmission?.let { admission ->
                        archive.writeRequest = NativeGalleryPcWriteRequest.prepare(app, this, owner, target, archive.permit,
                            archive.result!!, admission)
                        checkRow(); current()
                    }
                } finally { verifiedArchive.remove() }
            }
            return observation
        } finally {
            try { owner.close() }
            finally {
                try { if (archive?.ownsArchive == true) archive.archive?.close() }
                finally { NativeGalleryMediaIoLane.release(lane) }
            }
        }
    }

    /** Actual provider readback only, not durable history completion or Saved. */
    internal data class NativeGalleryPcProviderObservation(val row: JsonObject, val descriptor: JsonObject,
        val media: NativeIncomingMediaObservation, val journal: GalleryPcPreWriteRecord) {
        val isSavedReceipt: Boolean get() = false
        val grantsWriteAuthority: Boolean get() = false
    }
    private class VerifiedPcPostWrite(val target: NativeGalleryPcWriteTarget, val written: NativeGalleryPcWrittenBytesObservation,
        val expected: GalleryPcPreWriteRecord, val next: GalleryPcPreWriteRecord, val descriptor: ParcelFileDescriptor)
    private val verifiedPcPostWrite = ThreadLocal<VerifiedPcPostWrite?>()
    internal fun requireVerifiedPcPostWrite(target: NativeGalleryPcWriteTarget, written: NativeGalleryPcWrittenBytesObservation,
        expected: GalleryPcPreWriteRecord, next: GalleryPcPreWriteRecord) {
        val actual = verifiedPcPostWrite.get()
        if (actual == null || actual.target !== target || actual.written !== written || actual.expected !== expected ||
            actual.next !== next || !actual.descriptor.fileDescriptor.valid()) fail("gallery_pc_postwrite_native_proof_required")
        target.requireLocalWrittenOwner(index, written)
    }

    internal fun inspectPcWritten(target: NativeGalleryPcWriteTarget, written: NativeGalleryPcWrittenBytesObservation,
        lane: Any): NativeGalleryPcProviderObservation {
        if (Looper.myLooper() == Looper.getMainLooper() || Build.VERSION.SDK_INT < 30 || !NativeGalleryMediaIoLane.isOwnedBy(lane))
            fail("gallery_pc_postwrite_native_owner_required")
        val record = target.requireWrittenOwner(index, written); val original = record.stage.plan.predecessor
        if (record.state != "write_started") fail("gallery_pc_postwrite_original_operation_required")
        val oldRow = original.row!!; val uri = Uri.parse(oldRow.string("uri")); val mime = original.body.string("mime_type")
        val kind = written.media.mediaType
        fun current() { target.requireWrittenOwner(index, written) }
        fun observeNewRow(): NativeRow {
            val row = observeRow(kind, ::current, uri, mime,
                minOf(original.body.long("size"), written.bytes)..maxOf(original.body.long("size"), written.bytes), 0)
            if (row.witness.filterKeys { it != "revision" } != oldRow.filterKeys { it != "revision" } ||
                row.witness.string("revision").toLong() < oldRow.string("revision").toLong()) fail("gallery_pc_postwrite_row_changed")
            return row
        }
        val wait = java.util.concurrent.CountDownLatch(1)
        var row = observeNewRow(); var attempts = 0
        while (row.bytes != written.bytes || row.witness.string("revision").toLong() <= oldRow.string("revision").toLong()) {
            current()
            if (++attempts > 32) fail("gallery_pc_postwrite_provider_pending")
            val remaining = target.remainingWrittenMs()
            if (remaining <= 0) fail("gallery_pc_postwrite_provider_pending")
            wait.await(minOf(100L, remaining), java.util.concurrent.TimeUnit.MILLISECONDS)
            current(); row = observeNewRow()
        }
        val expectedRow = row.witness
        fun verify(descriptor: ParcelFileDescriptor): NativeGalleryPcProviderObservation {
            current(); val before = NativeGalleryPcWriteTarget.witness(descriptor)
            if (before != written.descriptor) fail("gallery_pc_postwrite_descriptor_changed")
            android.system.Os.lseek(descriptor.fileDescriptor, 0, android.system.OsConstants.SEEK_SET)
            val hash = MessageDigest.getInstance("SHA-256"); var bytes = 0L
            ParcelFileDescriptor.AutoCloseInputStream(ParcelFileDescriptor.dup(descriptor.fileDescriptor)).use { input ->
                val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
                try {
                    while (bytes < written.bytes) {
                        current(); val count = input.read(buffer, 0, minOf(buffer.size.toLong(), written.bytes - bytes).toInt()); current()
                        if (count <= 0) fail("gallery_pc_postwrite_content_changed")
                        hash.update(buffer, 0, count); bytes += count
                    }
                    if (input.read() != -1 || NativeHex.lower(hash.digest()) != written.sha256) fail("gallery_pc_postwrite_content_changed")
                } finally { buffer.fill(0) }
            }
            val media = NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, written.bytes, kind, mime, ensureNative = ::current)
            current()
            if (NativeGalleryPcWriteTarget.witness(descriptor) != before || observeNewRow().let { it.witness != expectedRow || it.bytes != written.bytes })
                fail("gallery_pc_postwrite_readback_changed")
            val next = record.verifyProvider(expectedRow, before)
            if (verifiedPcPostWrite.get() != null) fail("gallery_pc_postwrite_native_proof_required")
            verifiedPcPostWrite.set(VerifiedPcPostWrite(target, written, record, next, descriptor))
            try {
                target.recordProviderVerified(this, written, record, next)
                current()
                if (NativeGalleryPcWriteTarget.witness(descriptor) != before || observeNewRow().let { it.witness != expectedRow || it.bytes != written.bytes })
                    fail("gallery_pc_postwrite_readback_changed")
                return NativeGalleryPcProviderObservation(expectedRow, before, media, next)
            } finally { verifiedPcPostWrite.remove() }
        }
        val originalUri = MediaStore.setRequireOriginal(uri)
        if (Build.VERSION.SDK_INT >= 31) {
            val asset = resolver.openTypedAssetFileDescriptor(originalUri, "*/*", Bundle().apply {
                putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true)
            }, null) ?: fail("gallery_incoming_readback_missing")
            return asset.use {
                if (it.startOffset != 0L) fail("gallery_incoming_original_offset_changed")
                verify(it.parcelFileDescriptor)
            }
        }
        return (resolver.openFileDescriptor(originalUri, "r") ?: fail("gallery_incoming_readback_missing")).use(::verify)
    }

    private data class NativeRow(val witness: JsonObject, val pending: Long, val bytes: Long?)
    private fun observe(owner: NativeGalleryIncomingOwner, uri: Uri, mimeType: String, bytes: LongRange = 0L..0L): JsonObject =
        observeRow(owner, uri, mimeType, bytes, 1).witness

    private fun observeRow(owner: NativeGalleryIncomingOwner, uri: Uri, mimeType: String, bytes: LongRange,
        pending: Long?): NativeRow = observeRow(owner.kind, owner::requireCurrent, uri, mimeType, bytes, pending)

    private fun observeRow(kind: GalleryMediaType, current: () -> Unit, uri: Uri, mimeType: String, bytes: LongRange,
        pending: Long?): NativeRow {
        current()
        val volume = MediaStore.VOLUME_EXTERNAL_PRIMARY
        val id = uri.lastPathSegment?.toLongOrNull()?.takeIf { it > 0 } ?: fail("gallery_incoming_insert_invalid")
        if (uri != ContentUris.withAppendedId(kind.collection(volume, true), id) || volume !in MediaStore.getExternalVolumeNames(app))
            fail("gallery_incoming_insert_invalid")
        val namespace = MediaStore.getVersion(app, volume)
        val columns = arrayOf("_id", "_display_name", "mime_type", "relative_path", "_size", "date_added", "generation_added",
            "generation_modified", "is_pending", "is_trashed", "owner_package_name")
        val result = resolver.query(uri, columns, Bundle().apply {
            putInt(MediaStore.QUERY_ARG_MATCH_PENDING, MediaStore.MATCH_INCLUDE)
            putInt(MediaStore.QUERY_ARG_MATCH_TRASHED, MediaStore.MATCH_INCLUDE)
        }, null)?.use { cursor ->
            if (!cursor.moveToFirst()) fail("gallery_incoming_row_missing")
            fun text(name: String): String {
                val column = cursor.getColumnIndexOrThrow(name)
                if (cursor.getType(column) != Cursor.FIELD_TYPE_STRING) fail("gallery_incoming_row_changed")
                return cursor.getString(column)
            }
            fun number(name: String): Long {
                val column = cursor.getColumnIndexOrThrow(name)
                if (cursor.getType(column) != Cursor.FIELD_TYPE_INTEGER) fail("gallery_incoming_row_changed")
                return cursor.getLong(column)
            }
            val added = number("date_added"); val generation = number("generation_added"); val revision = number("generation_modified")
            val size = cursor.getColumnIndexOrThrow("_size")
            val actualPending = number("is_pending")
            if (number("_id") != id || actualPending !in 0L..1L || pending != null && actualPending != pending || number("is_trashed") != 0L ||
                text("owner_package_name") != app.packageName || text("relative_path") != path(kind) ||
                text("mime_type") != mimeType || added < 0 || generation <= 0 || revision < generation ||
                (if (cursor.isNull(size)) 0L !in bytes else number("_size") !in bytes)) fail("gallery_incoming_row_changed")
            NativeRow(buildJsonObject {
                put("uri", uri.toString()); put("namespace", namespace); put("volume", volume)
                put("member", "$id:$added:$generation"); put("revision", revision.toString()); put("path", path(kind))
                put("name", text("_display_name")); put("mime_type", mimeType); put("owner", app.packageName)
            }, actualPending, if (cursor.isNull(size)) null else number("_size")).also { if (cursor.moveToNext()) fail("gallery_incoming_row_changed") }
        } ?: fail("gallery_incoming_row_missing")
        current()
        if (MediaStore.getVersion(app, volume) != namespace) fail("gallery_incoming_namespace_changed")
        // Shared strict parser checks canonical URI, provider names and namespace.
        return result
    }
    private fun path(kind: GalleryMediaType) = if (kind == GalleryMediaType.IMAGES) "Pictures/Magnolie/" else "Movies/Magnolie/"
    private fun fail(code: String): Nothing = DeviceFileControl.fail(code)
}
