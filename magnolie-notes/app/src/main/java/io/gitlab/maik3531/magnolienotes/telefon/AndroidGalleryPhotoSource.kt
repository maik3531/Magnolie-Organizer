package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentResolver
import android.content.ContentUris
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.provider.MediaStore
import java.io.FilterInputStream
import java.io.InputStream
import java.text.Normalizer
import java.util.Locale

/** Only the selected native media domain/album. Metadata is not a frozen byte proof,
 * authoritative deletion inventory or permission to mutate phone photos.
 */
internal class AndroidGalleryPhotoSource(context: Context, private val scope: GalleryPhotoSourceScope) : PhotoSourceAccess {
    private val resolver = context.applicationContext.contentResolver
    private val modern get() = Build.VERSION.SDK_INT >= 29
    private fun fresh(lease: NativePhotoSourceLease, cancellation: CancellationSignal) {
        cancellation.throwIfCanceled()
        if (!scope.isCurrent(lease)) fail("gallery_inventory_source_revoked")
    }
    private fun collection(lease: GalleryPhotoSourceLease): Uri = lease.activation.mediaType.collection(lease.album.volume, modern)
    private fun projection(): Array<String> = arrayOf("_id", "bucket_id", "bucket_display_name", "_display_name",
        "mime_type", "_size", "date_modified", "date_added") +
        (if (modern) arrayOf("relative_path", "is_pending") else emptyArray()) +
         (if (Build.VERSION.SDK_INT >= 30) arrayOf("is_trashed", "generation_added", "generation_modified") else emptyArray())

    /** In-process scan position, not a URI, READ grant or deletion inventory.
     * Fresh native scope checks are mandatory on EVERY continuation query.
     */
    internal class Continuation internal constructor(internal val reader: AndroidGalleryPhotoSource,
        internal val lease: GalleryPhotoSourceLease, internal val after: Long)

    internal class Batch internal constructor(val inventory: PhotoSourceInventory, val continuation: Continuation?) {
        val reachedCurrentEnd: Boolean get() = continuation == null
        // MediaStore can change between queries, even when the current end was seen.
        val provesDeletion: Boolean get() = false
    }

    fun enumerateBatch(lease: GalleryPhotoSourceLease, continuation: Continuation? = null,
        cancellation: CancellationSignal = CancellationSignal(), maxFiles: Int = DeviceFileManifest.MAX_FILES): Batch {
        fresh(lease, cancellation)
        if (maxFiles !in 1..DeviceFileManifest.MAX_FILES) fail("gallery_inventory_file_limit")
        if (continuation != null && (continuation.reader !== this || continuation.lease !== lease || continuation.after <= 0))
            fail("gallery_inventory_continuation_changed")
        return enumerateBounded(lease, cancellation, continuation?.after ?: 0L, true, maxFiles)
    }

    fun enumerate(lease: GalleryPhotoSourceLease, cancellation: CancellationSignal = CancellationSignal()): PhotoSourceInventory {
        return enumerateBounded(lease, cancellation, 0L, false).inventory
    }

    private fun enumerateBounded(lease: GalleryPhotoSourceLease, cancellation: CancellationSignal,
        initialAfter: Long, batching: Boolean, maxFiles: Int = DeviceFileManifest.MAX_FILES): Batch {
        val started = SystemClock.elapsedRealtime()
        fun ready() {
            fresh(lease, cancellation)
            if (SystemClock.elapsedRealtime() - started > MAX_ELAPSED_MS) fail("gallery_inventory_deadline")
        }
        ready()
        var after = initialAfter
        var total = 0L
        val entries = mutableListOf<PhotoInventoryEntry>()
        val aliases = mutableSetOf<String>()
        // One extra bounded page is needed when an album ends at a page boundary.
        repeat(MAX_PAGES) {
            ready()
            val args = Bundle().apply {
                putString(ContentResolver.QUERY_ARG_SQL_SELECTION, "_id > ? AND bucket_id = ?" +
                    (if (modern) " AND is_pending = 0" else "") +
                    (if (Build.VERSION.SDK_INT >= 30) " AND is_trashed = 0" else ""))
                putStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, arrayOf(after.toString(), lease.album.bucketId))
                putString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER, "_id ASC")
                putInt(ContentResolver.QUERY_ARG_LIMIT, PAGE_SIZE)
            }
            val cursor = resolver.query(collection(lease), projection(), args, cancellation)
                ?: fail("gallery_inventory_provider_unavailable")
            var count = 0
            cursor.use {
                while (true) {
                    ready()
                    if (!it.moveToNext()) break
                    ready()
                    if (++count > PAGE_SIZE) fail("gallery_inventory_page_limit")
                    val entry = member(lease, it)
                    val id = entry.documentId.substringBefore(':').toLong()
                    if (id <= after) fail("gallery_inventory_page_order")
                    if (batching && (entries.size >= maxFiles ||
                            total + entry.advertisedBytes > DeviceFileManifest.MAX_TOTAL_BYTES)) {
                        // Look ahead without consuming this member. The next batch
                        // queries after the last INCLUDED row, never after this row.
                        ready()
                        return Batch(PhotoSourceInventory(lease, entries), Continuation(this, lease, after))
                    }
                    after = id
                    if (entries.size >= DeviceFileManifest.MAX_FILES) fail("gallery_inventory_file_limit")
                    total += entry.advertisedBytes
                    if (total > DeviceFileManifest.MAX_TOTAL_BYTES) fail("gallery_inventory_total_limit")
                    val alias = Normalizer.normalize(entry.relativePath.uppercase(Locale.ROOT).lowercase(Locale.ROOT)
                        .uppercase(Locale.ROOT), Normalizer.Form.NFC)
                    if (!aliases.add(alias)) fail("gallery_inventory_path_alias")
                    entries += entry
                }
            }
            ready()
            if (count < PAGE_SIZE) return Batch(PhotoSourceInventory(lease, entries), null)
        }
        fail("gallery_inventory_page_limit")
    }

    private fun member(lease: GalleryPhotoSourceLease, cursor: Cursor, trashed: Boolean = false): PhotoInventoryEntry {
        fun text(name: String): String {
            val column = cursor.getColumnIndexOrThrow(name)
            if (cursor.getType(column) != Cursor.FIELD_TYPE_STRING) fail("gallery_inventory_invalid_metadata")
            return cursor.getString(column)
        }
        fun number(name: String): Long {
            val column = cursor.getColumnIndexOrThrow(name)
            if (cursor.getType(column) != Cursor.FIELD_TYPE_INTEGER) fail("gallery_inventory_invalid_metadata")
            return cursor.getLong(column)
        }
        val id = number("_id")
        val bucketColumn = cursor.getColumnIndexOrThrow("bucket_id")
        if (cursor.getType(bucketColumn) !in setOf(Cursor.FIELD_TYPE_STRING, Cursor.FIELD_TYPE_INTEGER) ||
            cursor.getString(bucketColumn) != lease.album.bucketId || text("bucket_display_name") != lease.album.displayName ||
            modern && (text("relative_path") != lease.album.relativePath || number("is_pending") != 0L) ||
            Build.VERSION.SDK_INT >= 30 && number("is_trashed") != (if (trashed) 1L else 0L))
            fail("gallery_inventory_album_changed")
        val name = text("_display_name")
        val bytes = number("_size")
        val modified = number("date_modified")
        val added = number("date_added")
        val insertionGeneration = if (Build.VERSION.SDK_INT >= 30) number("generation_added") else null
        val revision = if (Build.VERSION.SDK_INT >= 30) number("generation_modified") else null
        if (id <= 0 || !lease.activation.mediaType.acceptsMime(text("mime_type")) ||
            '/' in name || !DeviceFileManifest.portablePath(name) || bytes !in 0..DeviceFileManifest.MAX_FILE_BYTES ||
            modified !in 0..Long.MAX_VALUE / 1000 || added < 0 ||
            insertionGeneration != null && (insertionGeneration < 0 || revision == null || revision < insertionGeneration))
            fail("gallery_inventory_invalid_metadata")
        // Opaque native member witness: row ID + insertion timestamp and API30+
        // insertion generation. Modification generation is a separate revision
        // so cropping does not manufacture a different photo correlation ID.
        // Never treated as a content digest or an independently granted URI.
        val nativeMember = "$id:$added" + (insertionGeneration?.let { ":$it" } ?: "")
        return PhotoInventoryEntry(ContentUris.withAppendedId(collection(lease), id).toString(), nativeMember, name, bytes, modified * 1000, revision?.toString())
    }

    private fun document(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal): Uri {
        fresh(lease, cancellation)
        if (lease !is GalleryPhotoSourceLease || !Regex("[1-9][0-9]{0,18}:(0|[1-9][0-9]{0,18})(:(0|[1-9][0-9]{0,18}))?").matches(entry.documentId))
            fail("gallery_inventory_invalid_member")
        val id = entry.documentId.substringBefore(':').toLongOrNull() ?: fail("gallery_inventory_invalid_member")
        val uri = ContentUris.withAppendedId(collection(lease), id)
        if (uri.toString() != entry.documentUri) fail("gallery_inventory_invalid_member")
        return uri
    }

    internal fun observeOriginalForRecovery(lease: GalleryPhotoSourceLease, origin: GalleryPhotoOrigin,
        file: DeviceManifestFile, cancellation: CancellationSignal): PhotoInventoryEntry {
        fresh(lease, cancellation)
        if (Build.VERSION.SDK_INT < 30 || lease.access.mediaStoreVersion == null || origin.nativeRevision == null ||
            origin.nativeMember.split(':').getOrNull(2)?.toLongOrNull()?.let { it > 0 } != true)
            fail("gallery_archive_native_origin_required")
        val row = origin.nativeMember.substringBefore(':').toLongOrNull() ?: fail("gallery_inventory_invalid_member")
        val uri = ContentUris.withAppendedId(collection(lease), row)
        val observed = resolver.query(uri, projection(), Bundle(), cancellation)?.use {
            fresh(lease, cancellation)
            if (!it.moveToFirst()) fail("gallery_inventory_member_missing")
            member(lease, it).also { value ->
                if (it.moveToNext() || value.documentId != origin.nativeMember || value.nativeRevision != origin.nativeRevision ||
                    value.relativePath != file.path || value.advertisedBytes != file.size) fail("gallery_inventory_member_changed")
            }
        } ?: fail("gallery_inventory_member_missing")
        fresh(lease, cancellation); return observed
    }

    internal fun observeRecoveryMime(lease: GalleryPhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal): String {
        val uri = document(lease, entry, cancellation)
        val mime = resolver.query(uri, projection(), Bundle(), cancellation)?.use {
            fresh(lease, cancellation)
            if (!it.moveToFirst() || member(lease, it) != entry) fail("gallery_inventory_member_changed")
            it.getString(it.getColumnIndexOrThrow("mime_type")).also { _ ->
                if (it.moveToNext()) fail("gallery_inventory_member_changed")
            }
        } ?: fail("gallery_inventory_member_missing")
        fresh(lease, cancellation); return mime
    }

    /** Re-resolve a protected archive origin through a NEW native READ lease.
     * The archived URI is compared, never used as an independent READ grant. */
    internal fun observeArchivedOriginalForWrite(lease: GalleryPhotoSourceLease, origin: kotlinx.serialization.json.JsonObject,
        archived: NativeGalleryArchiveEntry, cancellation: CancellationSignal): PhotoInventoryEntry {
        fresh(lease, cancellation)
        if (Build.VERSION.SDK_INT < 30 || !archived.originalBytesVerified ||
            lease.access.coverage == GalleryReadCoverage.SELECTED_ONLY || lease.access.mediaStoreVersion != origin.string("namespace") ||
            lease.sourceKey != origin.string("source") || lease.album.volume != origin.string("volume") ||
            lease.album.relativePath != origin.string("album_path") || lease.activation.mediaType.uriSegment != origin.string("media_type") ||
            lease.receiver.peerId != origin.string("peer") || lease.receiver.identitySha256 != origin.string("peer_identity"))
            fail("gallery_write_original_scope_changed")
        val member = origin.string("member")
        if (!Regex("[1-9][0-9]{0,18}:(0|[1-9][0-9]{0,18}):[1-9][0-9]{0,18}").matches(member))
            fail("gallery_archive_native_origin_required")
        val row = member.substringBefore(':').toLongOrNull() ?: fail("gallery_inventory_invalid_member")
        val uri = ContentUris.withAppendedId(collection(lease), row)
        if (uri.toString() != origin.string("uri")) fail("gallery_write_original_scope_changed")
        val observed = resolver.query(uri, projection(), Bundle(), cancellation)?.use {
            fresh(lease, cancellation)
            if (!it.moveToFirst()) fail("gallery_inventory_member_missing")
            member(lease, it).also { value ->
                if (value.documentId != member || value.nativeRevision != origin.string("revision") ||
                    value.relativePath != archived.displayName || value.advertisedBytes != archived.bytes ||
                    it.getString(it.getColumnIndexOrThrow("mime_type")) != origin.string("mime_type") || it.moveToNext())
                    fail("gallery_inventory_member_changed")
            }
        } ?: fail("gallery_inventory_member_missing")
        fresh(lease, cancellation); return observed
    }

    override fun verifyMetadata(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal) {
        val uri = document(lease, entry, cancellation)
        if (lease !is GalleryPhotoSourceLease) fail("gallery_inventory_invalid_member")
        resolver.query(uri, projection(), Bundle(), cancellation)?.use {
            fresh(lease, cancellation)
            if (!it.moveToFirst()) fail("gallery_inventory_member_missing")
            fresh(lease, cancellation)
            if (member(lease, it) != entry || it.moveToNext()) fail("gallery_inventory_member_changed")
            fresh(lease, cancellation)
        } ?: fail("gallery_inventory_member_missing")
        fresh(lease, cancellation)
    }

    /** Only called on the owned source lane AFTER durable action preparation.
     * Generation/insertion predicates are evaluated by the provider mutation,
     * not merely by an earlier app-side query. Never permanently deletes. */
    internal fun trashOriginal(lease: GalleryPhotoSourceLease, entry: PhotoInventoryEntry, mime: String,
        archived: NativeGalleryArchiveEntry, cancellation: CancellationSignal, current: () -> Unit) {
        current(); verifyMetadata(lease, entry, cancellation)
        val uri = document(lease, entry, cancellation)
        val parts = entry.documentId.split(':')
        if (Build.VERSION.SDK_INT < 30 || parts.size != 3 || entry.nativeRevision == null || !archived.originalBytesVerified)
            fail("gallery_archive_native_origin_required")
        val selection = "_id = ? AND bucket_id = ? AND relative_path = ? AND _display_name = ? AND _size = ? AND date_added = ? AND generation_added = ? AND generation_modified = ? AND mime_type = ? AND is_pending = 0 AND is_trashed = 0"
        val arguments = arrayOf(parts[0], lease.album.bucketId, lease.album.relativePath!!, entry.relativePath,
            entry.advertisedBytes.toString(), parts[1], parts[2], entry.nativeRevision, mime)
        current()
        val changed = resolver.update(uri, android.content.ContentValues().apply { put(MediaStore.MediaColumns.IS_TRASHED, 1) }, selection, arguments)
        if (changed != 1) fail("gallery_write_conditional_update_not_proven")
        current()
        fun readback(): PhotoInventoryEntry {
            current(); fresh(lease, cancellation)
            return resolver.query(uri, projection(), Bundle().apply {
                putInt(MediaStore.QUERY_ARG_MATCH_TRASHED, MediaStore.MATCH_INCLUDE)
            }, cancellation)?.use {
                current()
                if (!it.moveToFirst()) fail("gallery_write_trashed_readback_missing")
                member(lease, it, trashed = true).also { value ->
                    if (value.documentId != entry.documentId || value.relativePath != entry.relativePath ||
                        value.advertisedBytes != archived.bytes || value.nativeRevision?.toLongOrNull()?.let { revision ->
                            revision > entry.nativeRevision.toLong() } != true ||
                        it.getString(it.getColumnIndexOrThrow("mime_type")) != mime || it.moveToNext())
                        fail("gallery_write_trashed_readback_changed")
                }
            } ?: fail("gallery_write_trashed_readback_missing")
        }
        val trashed = readback()
        val stream = originalStream(uri, cancellation)
        val hash = java.security.MessageDigest.getInstance("SHA-256"); var bytes = 0L
        stream.use { input ->
            val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
            try {
                while (true) {
                    current(); fresh(lease, cancellation); val count = input.read(buffer)
                    if (count == -1) break
                    if (count <= 0 || bytes + count > archived.bytes) fail("gallery_write_trashed_content_changed")
                    hash.update(buffer, 0, count); bytes += count
                }
            } finally { buffer.fill(0) }
        }
        if (bytes != archived.bytes || hash.digest().joinToString("") { "%02x".format(it) } != archived.sha256 || readback() != trashed)
            fail("gallery_write_trashed_content_changed")
        current(); fresh(lease, cancellation)
    }

    private fun originalStream(uri: Uri, cancellation: CancellationSignal): InputStream {
        val requested = MediaStore.setRequireOriginal(uri)
        return if (Build.VERSION.SDK_INT >= 31) {
            val options = Bundle().apply { putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true) }
            val descriptor = resolver.openTypedAssetFileDescriptor(requested, "*/*", options, cancellation)
                ?: fail("gallery_inventory_member_missing")
            try { descriptor.createInputStream() } catch (error: Exception) { descriptor.close(); throw error }
        } else {
            val descriptor = resolver.openFileDescriptor(requested, "r", cancellation) ?: fail("gallery_inventory_member_missing")
            ParcelFileDescriptor.AutoCloseInputStream(descriptor)
        }
    }

    override fun openRead(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal): InputStream =
        openChecked(lease, entry, cancellation, original = false)

    internal fun openOriginalForRecovery(lease: GalleryPhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal): InputStream {
        if (Build.VERSION.SDK_INT < 30) fail("gallery_archive_native_origin_required")
        return openChecked(lease, entry, cancellation, original = true)
    }

    private fun openChecked(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal, original: Boolean): InputStream {
        val uri = document(lease, entry, cancellation)
        verifyMetadata(lease, entry, cancellation)
        // No fallback: normal READ can redact EXIF. Recovery must preserve the
        // original, or fail before any destructive operation is authorized.
        val stream = if (original) originalStream(uri, cancellation) else {
            val descriptor = resolver.openFileDescriptor(uri, "r", cancellation) ?: fail("gallery_inventory_member_missing")
            ParcelFileDescriptor.AutoCloseInputStream(descriptor)
        }
        try {
            fresh(lease, cancellation)
            verifyMetadata(lease, entry, cancellation)
        } catch (error: Exception) { stream.close(); throw error }
        return object : FilterInputStream(stream) {
            override fun read(): Int {
                fresh(lease, cancellation)
                return `in`.read().also { fresh(lease, cancellation) }
            }
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                fresh(lease, cancellation)
                return `in`.read(buffer, offset, length).also { fresh(lease, cancellation) }
            }
        }
    }

    companion object {
        const val PAGE_SIZE = 32
        const val MAX_PAGES = DeviceFileManifest.MAX_FILES / PAGE_SIZE + 1
        const val MAX_ELAPSED_MS = 30_000L
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
