package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Looper
import android.provider.MediaStore
import kotlinx.serialization.json.*
import java.util.concurrent.atomic.AtomicBoolean

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

/** Actual new app-owned PENDING MediaStore rows only. No bytes, publication,
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

    private fun observe(owner: NativeGalleryIncomingOwner, uri: Uri, mimeType: String): JsonObject {
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
            if (number("_id") != id || number("is_pending") != 1L || number("is_trashed") != 0L ||
                text("owner_package_name") != app.packageName || text("relative_path") != path(owner.kind) ||
                text("mime_type") != mimeType || added < 0 || generation <= 0 || revision < generation ||
                !cursor.isNull(size) && number("_size") != 0L) fail("gallery_incoming_row_changed")
            buildJsonObject {
                put("uri", uri.toString()); put("namespace", namespace); put("volume", volume)
                put("member", "$id:$added:$generation"); put("revision", revision.toString()); put("path", path(owner.kind))
                put("name", text("_display_name")); put("mime_type", mimeType); put("owner", app.packageName)
            }.also { if (cursor.moveToNext()) fail("gallery_incoming_row_changed") }
        } ?: fail("gallery_incoming_row_missing")
        owner.requireCurrent()
        if (MediaStore.getVersion(app, volume) != namespace) fail("gallery_incoming_namespace_changed")
        // Shared strict parser checks canonical URI, provider names and namespace.
        return result
    }
    private fun path(kind: GalleryMediaType) = if (kind == GalleryMediaType.IMAGES) "Pictures/Magnolie/" else "Movies/Magnolie/"
    private fun fail(code: String): Nothing = DeviceFileControl.fail(code)
}
