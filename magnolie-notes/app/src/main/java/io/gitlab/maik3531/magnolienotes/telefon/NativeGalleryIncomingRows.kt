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
    internal val manifest: DeviceFileManifest, internal val kind: GalleryMediaType) : AutoCloseable {
    private val token = incomingIntent() as? MediaSyncTransport.IntentToken ?: fail()
    private val originalPeer = peer()?.takeIf { it.allowed && it.pairingEpoch != null } ?: fail()
    internal val pairingEpoch = originalPeer.pairingEpoch!!
    internal val binding = session.binding(manifest.fingerprint) ?: fail()
    private val policy = index.galleryPolicy()
    private val issued = DeviceFileControl.monotonicMs()
    private var last = issued
    private val ended = AtomicBoolean(false)
    init { requireCurrent() }

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
            if (!current.allowed || current.owner !== originalPeer.owner || current.peerId != originalPeer.peerId ||
                current.identitySha256 != originalPeer.identitySha256 || current.pairingEpoch != pairingEpoch ||
                session.binding(manifest.fingerprint) != binding || index.galleryPolicy() != policy || policy.repairPending ||
                policy.policy?.let { it.receiverId == current.peerId && it.receiverIdentitySha256 == current.identitySha256 &&
                    it.pairingEpoch == pairingEpoch && it.receiving?.enabled(kind) == true } != true ||
                binding.senderId != manifest.senderId || binding.receiverId != manifest.receiverId ||
                binding.senderId != current.peerId || binding.senderIdentitySha256 != current.identitySha256) fail()
        } catch (error: Exception) { ended.set(true); throw error }
    }
    override fun close() { ended.set(true) }
    companion object {
        internal fun capture(session: NativeFileControlSession, index: PhotoSourceJobIndex, book: NativeGalleryReceiveBookPermit,
            currentPeer: () -> NativeFileControlPeer?, incomingIntent: () -> Any?, manifest: DeviceFileManifest,
            kind: GalleryMediaType): NativeGalleryIncomingOwner {
            if (Build.VERSION.SDK_INT < 30 || Looper.myLooper() == Looper.getMainLooper()) fail()
            return NativeGalleryIncomingOwner(session, index, book, currentPeer, incomingIntent, manifest, kind)
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

    internal fun prepare(owner: NativeGalleryIncomingOwner, fileId: String, mimeType: String): GalleryIncomingPublication {
        if (Looper.myLooper() == Looper.getMainLooper() || Build.VERSION.SDK_INT < 30)
            fail("gallery_incoming_io_android30_required")
        owner.requireCurrent()
        val planned = GalleryIncomingPublication.plan(owner.binding, owner.manifest, fileId, owner.pairingEpoch, owner.kind, mimeType)
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
            owner.kind, body.string("mime_type"))
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
        cancellation: CancellationSignal) {
        fun current() { cancellation.throwIfCanceled(); owner.requireCurrent() }
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
        val expected = GalleryIncomingPublication.plan(owner.binding, owner.manifest, fileId, owner.pairingEpoch, owner.kind, body.string("mime_type"))
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
                NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, size, owner.kind, mime, ::current)
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

    private data class NativeRow(val witness: JsonObject, val pending: Long)
    private fun observe(owner: NativeGalleryIncomingOwner, uri: Uri, mimeType: String, bytes: LongRange = 0L..0L): JsonObject =
        observeRow(owner, uri, mimeType, bytes, 1).witness

    private fun observeRow(owner: NativeGalleryIncomingOwner, uri: Uri, mimeType: String, bytes: LongRange,
        pending: Long?): NativeRow {
        owner.requireCurrent()
        val volume = MediaStore.VOLUME_EXTERNAL_PRIMARY
        val id = uri.lastPathSegment?.toLongOrNull()?.takeIf { it > 0 } ?: fail("gallery_incoming_insert_invalid")
        if (uri != ContentUris.withAppendedId(owner.kind.collection(volume, true), id) || volume !in MediaStore.getExternalVolumeNames(app))
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
                text("owner_package_name") != app.packageName || text("relative_path") != path(owner.kind) ||
                text("mime_type") != mimeType || added < 0 || generation <= 0 || revision < generation ||
                (if (cursor.isNull(size)) 0L !in bytes else number("_size") !in bytes)) fail("gallery_incoming_row_changed")
            NativeRow(buildJsonObject {
                put("uri", uri.toString()); put("namespace", namespace); put("volume", volume)
                put("member", "$id:$added:$generation"); put("revision", revision.toString()); put("path", path(owner.kind))
                put("name", text("_display_name")); put("mime_type", mimeType); put("owner", app.packageName)
            }, actualPending).also { if (cursor.moveToNext()) fail("gallery_incoming_row_changed") }
        } ?: fail("gallery_incoming_row_missing")
        owner.requireCurrent()
        if (MediaStore.getVersion(app, volume) != namespace) fail("gallery_incoming_namespace_changed")
        // Shared strict parser checks canonical URI, provider names and namespace.
        return result
    }
    private fun path(kind: GalleryMediaType) = if (kind == GalleryMediaType.IMAGES) "Pictures/Magnolie/" else "Movies/Magnolie/"
    private fun fail(code: String): Nothing = DeviceFileControl.fail(code)
}
