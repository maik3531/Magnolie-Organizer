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
import androidx.activity.ComponentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import kotlinx.serialization.json.*
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

/** Explicit LOCAL foreground selection. No historical pairing, URI permission,
 * remote confirmed boolean, or read-source lease can create this owner. */
internal class NativeGalleryRestoreSession private constructor(private val activity: ComponentActivity,
    internal val selected: NativeGalleryTrashAction, internal val permit: NativeGalleryTrashBookPermit) : DefaultLifecycleObserver, AutoCloseable {
    private val issued = DeviceFileControl.monotonicMs()
    private var last = issued
    private var revoked = false
    private val used = AtomicBoolean(false)
    init { requireCurrent(); activity.lifecycle.addObserver(this) }
    @Synchronized internal fun requireCurrent() {
        val now = DeviceFileControl.monotonicMs()
        if (revoked || now < issued || now < last || now - issued >= DeviceFileControl.MAX_TTL_MS ||
            activity.isFinishing || activity.isDestroyed || !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) {
            revoked = true; fail("gallery_restore_foreground_not_current")
        }
        try { permit.requireCurrent() } catch (error: Exception) { revoked = true; throw error }
        last = now
    }
    internal fun consume() { requireCurrent(); if (!used.compareAndSet(false, true)) fail("gallery_restore_selection_already_used") }
    override fun onPause(owner: LifecycleOwner) { synchronized(this) { revoked = true } }
    override fun onDestroy(owner: LifecycleOwner) { close() }
    override fun close() { synchronized(this) { revoked = true }; activity.lifecycle.removeObserver(this) }
    companion object {
        fun capture(activity: ComponentActivity, selected: NativeGalleryTrashAction, permit: NativeGalleryTrashBookPermit): NativeGalleryRestoreSession {
            if (Looper.myLooper() != Looper.getMainLooper()) fail("gallery_permission_ui_thread_required")
            if (selected.state !in setOf("trashed", "restore_row_prepared")) fail("gallery_archive_stale_action")
            return NativeGalleryRestoreSession(activity, selected, permit)
        }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}

/** Restores a NEW app-owned pending row only. Never opens or untrashes the old
 * source URI, overwrites an existing filename, or destroys the recovery copy.
 * Interrupted insert/copy/publication remains journal-held, never auto-retried.
 */
internal class NativeGalleryMediaRestore(context: Context) {
    private val app = context.applicationContext
    private val resolver = app.contentResolver
    private data class Row(val witness: JsonObject, val bytes: Long?, val pending: Long)

    fun restore(archive: NativeGalleryTrashArchive, session: NativeGalleryRestoreSession,
        cancellation: CancellationSignal): NativeGalleryTrashAction {
        fun active() { cancellation.throwIfCanceled(); session.requireCurrent() }
        active()
        if (Build.VERSION.SDK_INT < 30) fail("gallery_restore_android30_required")
        val selected = session.selected
        val entry = archive.entries(session.permit).singleOrNull { it.id == selected.archiveId && it.version == selected.archiveVersion }
            ?: fail("gallery_archive_stale_selection")
        val origin = archive.verifiedOriginalOrigin(entry, session.permit)
        val kind = GalleryMediaType.entries.single { it.uriSegment == origin.string("media_type") }
        val volume = origin.string("volume"); val path = origin.string("album_path")
        // Keep authenticated album placement, never a caller-provided path or
        // traversal. Refuse unsupported destinations rather than silently move.
        if (!path.endsWith('/') || path.dropLast(1).split('/').any { !DeviceFileManifest.portablePath(it) || it in setOf(".", "..") } ||
            path.substringBefore('/') !in (if (kind == GalleryMediaType.VIDEO) setOf("DCIM", "Movies", "Pictures") else setOf("DCIM", "Pictures")))
            fail("gallery_restore_album_path_unsupported")
        fun namespace(): String {
            active()
            if (volume !in MediaStore.getExternalVolumeNames(app)) fail("gallery_restore_volume_not_mounted")
            return MediaStore.getVersion(app, volume).also {
                if (it.length !in 1..1024 || it.any { ch -> ch.code < 32 || ch.code == 127 }) fail("gallery_restore_namespace_invalid")
            }
        }
        val namespace = namespace()
        fun current() { active(); if (namespace() != namespace) fail("gallery_restore_namespace_changed") }
        session.consume()
        val collection = kind.collection(volume, true)
        val recovering = selected.state == "restore_row_prepared"
        var prepared: NativeGalleryTrashAction? = null
        val uri = if (recovering) {
            // Recover ONLY the exact protected row. No reinsertion, rewriting,
            // name-based adoption, missing-row success, or historical URI grant.
            if (archive.actions(session.permit).none { it == selected } || selected.restoredMember == null ||
                selected.restoredMember.string("namespace") != namespace) fail("gallery_archive_stale_action")
            Uri.parse(selected.restoredMember.string("uri"))
        } else {
            prepared = archive.prepareRestore(selected, session.permit, ::current)
            current()
            resolver.insert(collection, ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, entry.displayName)
                put(MediaStore.MediaColumns.MIME_TYPE, origin.string("mime_type"))
                put(MediaStore.MediaColumns.RELATIVE_PATH, path)
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }) ?: fail("gallery_restore_insert_not_proven")
        }
        // Insert is the only row creation. No fallback to a named existing row.
        val id = uri.lastPathSegment?.toLongOrNull()?.takeIf { it > 0 } ?: fail("gallery_restore_insert_not_proven")
        if (uri != ContentUris.withAppendedId(collection, id) || uri.toString() == origin.string("uri")) fail("gallery_restore_new_row_required")
        fun observe(pending: Long?): Row {
            current()
            val columns = arrayOf("_id", "_display_name", "mime_type", "relative_path", "_size", "date_added",
                "generation_added", "generation_modified", "is_pending", "is_trashed", "owner_package_name")
            return resolver.query(uri, columns, Bundle().apply {
                putInt(MediaStore.QUERY_ARG_MATCH_PENDING, MediaStore.MATCH_INCLUDE)
                putInt(MediaStore.QUERY_ARG_MATCH_TRASHED, MediaStore.MATCH_INCLUDE)
            }, cancellation)?.use { cursor ->
                current()
                if (!cursor.moveToFirst()) fail("gallery_restore_row_missing")
                fun text(name: String): String {
                    val column = cursor.getColumnIndexOrThrow(name)
                    if (cursor.getType(column) != Cursor.FIELD_TYPE_STRING) fail("gallery_restore_row_changed")
                    return cursor.getString(column)
                }
                fun number(name: String): Long {
                    val column = cursor.getColumnIndexOrThrow(name)
                    if (cursor.getType(column) != Cursor.FIELD_TYPE_INTEGER) fail("gallery_restore_row_changed")
                    return cursor.getLong(column)
                }
                val name = text("_display_name"); val added = number("date_added")
                val inserted = number("generation_added"); val revision = number("generation_modified")
                val size = if (cursor.isNull(cursor.getColumnIndexOrThrow("_size"))) null else number("_size")
                val actualPending = number("is_pending")
                if (number("_id") != id || actualPending !in 0..1 || pending != null && actualPending != pending || number("is_trashed") != 0L ||
                    text("owner_package_name") != app.packageName || text("relative_path") != path ||
                    text("mime_type") != origin.string("mime_type") || !DeviceFileManifest.portablePath(name) || '/' in name ||
                    added < 0 || inserted <= 0 || revision < inserted || size?.let { it !in 0..entry.bytes } == true)
                    fail("gallery_restore_row_changed")
                val result = Row(buildJsonObject {
                    put("uri", uri.toString()); put("member", "$id:$added:$inserted"); put("revision", revision.toString())
                    put("namespace", namespace); put("volume", volume); put("media_type", kind.uriSegment)
                    put("path", path); put("name", name); put("mime_type", origin.string("mime_type"))
                }, size, actualPending)
                if (cursor.moveToNext()) fail("gallery_restore_row_changed")
                result
            } ?: fail("gallery_restore_row_missing")
        }
        val inserted = observe(if (recovering) null else 1)
        val held = if (recovering) {
            if (inserted.witness.filterKeys { it != "revision" } != selected.restoredMember!!.filterKeys { it != "revision" } ||
                inserted.witness.string("revision").toLong() < selected.restoredMember.string("revision").toLong()) fail("gallery_restore_row_changed")
            selected
        } else archive.recordRestoreRow(prepared!!, inserted.witness, session.permit, ::current)
        if (!recovering) {
            current()
            if (observe(1) != inserted) fail("gallery_restore_row_changed")
            val descriptor = resolver.openFileDescriptor(uri, "w", cancellation) ?: fail("gallery_restore_output_missing")
            ParcelFileDescriptor.AutoCloseOutputStream(descriptor).use { output ->
                archive.readContent(entry, session.permit) { bytes -> current(); output.write(bytes); current() }
                output.flush(); descriptor.fileDescriptor.sync(); current()
            }
        }
        val copied = observe(inserted.pending)
        fun sameMember(first: Row, second: Row) = first.witness.filterKeys { it != "revision" } == second.witness.filterKeys { it != "revision" } &&
            second.witness.string("revision").toLong() >= first.witness.string("revision").toLong()
        if (!sameMember(inserted, copied) || copied.bytes != entry.bytes) fail("gallery_restore_copy_metadata_changed")
        fun verifyBytes() {
            current()
            val original = MediaStore.setRequireOriginal(uri)
            val stream = if (Build.VERSION.SDK_INT >= 31) {
                val asset = resolver.openTypedAssetFileDescriptor(original, "*/*", Bundle().apply {
                    putBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT, true)
                }, cancellation) ?: fail("gallery_restore_readback_missing")
                try { asset.createInputStream() } catch (error: Exception) { asset.close(); throw error }
            } else ParcelFileDescriptor.AutoCloseInputStream(resolver.openFileDescriptor(original, "r", cancellation)
                ?: fail("gallery_restore_readback_missing"))
            val hash = MessageDigest.getInstance("SHA-256"); var size = 0L
            stream.use { input ->
                val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
                try {
                    while (true) {
                        current(); val count = input.read(buffer)
                        if (count == -1) break
                        if (count <= 0 || size + count > entry.bytes) fail("gallery_restore_content_changed")
                        size += count; hash.update(buffer, 0, count)
                    }
                } finally { buffer.fill(0) }
            }
            if (size != entry.bytes || hash.digest().joinToString("") { "%02x".format(it) } != entry.sha256) fail("gallery_restore_content_changed")
            current()
        }
        verifyBytes()
        if (observe(copied.pending) != copied) fail("gallery_restore_copy_metadata_changed")
        if (copied.pending == 1L) {
            val parts = copied.witness.string("member").split(':')
            current()
            val changed = resolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                "_id = ? AND date_added = ? AND generation_added = ? AND generation_modified = ? AND owner_package_name = ? AND is_pending = 1 AND is_trashed = 0",
                arrayOf(parts[0], parts[1], parts[2], copied.witness.string("revision"), app.packageName))
            if (changed != 1) fail("gallery_restore_publish_not_proven")
        }
        val published = observe(0)
        if (!sameMember(copied, published) || published.bytes != entry.bytes ||
            copied.pending == 1L && published.witness.string("revision").toLong() <= copied.witness.string("revision").toLong() ||
            published.witness.string("revision").toLong() <= held.restoredMember!!.string("revision").toLong()) fail("gallery_restore_publish_not_proven")
        verifyBytes()
        if (observe(0) != published) fail("gallery_restore_publish_not_proven")
        return archive.finishRestore(held, published.witness, session.permit, ::current)
    }

    companion object { private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code) }
}
