package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.ContentResolver
import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.CancellationSignal
import android.os.SystemClock
import android.provider.MediaStore
import java.util.Collections
import java.util.Locale

internal enum class GallerySourceKind { CAMERA, WHATSAPP_RECEIVED, SCREENSHOTS, DOWNLOADS }
internal enum class GalleryReadCoverage { NONE, SELECTED_ONLY, FULL_IMAGES, FULL_VIDEOS }

/** Supplied by authenticated desktop policy, never inferred from a device name. */
internal class NativeGalleryRequest(val receiver: NativePhotoReceiver, val policyEpoch: String, kinds: Set<GallerySourceKind>,
    val mediaType: GalleryMediaType = GalleryMediaType.IMAGES, val mediaIntent: Any? = null) {
    val kinds: Set<GallerySourceKind> = Collections.unmodifiableSet(kinds.toSet())
    init { require(Regex("[0-9a-f]{64}").matches(policyEpoch)) }
}

internal data class GalleryAlbumCandidate(val kind: GallerySourceKind, val volume: String, val bucketId: String,
    val displayName: String, val relativePath: String?, val visibleImageCount: Long, val needsAlbumChoice: Boolean)

internal class GalleryAlbumCatalog(val coverage: GalleryReadCoverage, entries: List<GalleryAlbumCandidate>,
    internal val activation: NativeGalleryRequest? = null, internal val accessEpoch: String? = null) {
    val albums: List<GalleryAlbumCandidate> = Collections.unmodifiableList(entries.toList())
    val policyEpoch: String? get() = activation?.policyEpoch
    // Even full photo permission + an album list is NOT a complete file inventory.
    val provesFileDeletion: Boolean get() = false
}

internal object GallerySourceRules {
    private val folders = mapOf(
        GallerySourceKind.CAMERA to listOf("DCIM/Camera/", "Pictures/Camera/", "DCIM/100ANDRO/", "DCIM/100MEDIA/"),
        GallerySourceKind.WHATSAPP_RECEIVED to listOf("WhatsApp/Media/WhatsApp Images/", "WhatsApp Business/Media/WhatsApp Business Images/",
            "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/",
            "Android/media/com.whatsapp.w4b/WhatsApp Business/Media/WhatsApp Business Images/"),
        GallerySourceKind.SCREENSHOTS to listOf("Pictures/Screenshots/", "DCIM/Screenshots/"),
        GallerySourceKind.DOWNLOADS to listOf("Download/", "Downloads/"))
    private val labels = mapOf(GallerySourceKind.CAMERA to listOf("Camera", "100ANDRO", "100MEDIA"),
        GallerySourceKind.WHATSAPP_RECEIVED to listOf("WhatsApp Images", "WhatsApp Business Images"),
        GallerySourceKind.SCREENSHOTS to listOf("Screenshots"), GallerySourceKind.DOWNLOADS to listOf("Download", "Downloads"))
    private val videoFolders = mapOf(
        GallerySourceKind.CAMERA to listOf("DCIM/Camera/", "Movies/Camera/", "DCIM/100ANDRO/", "DCIM/100MEDIA/"),
        GallerySourceKind.WHATSAPP_RECEIVED to listOf("WhatsApp/Media/WhatsApp Video/", "WhatsApp Business/Media/WhatsApp Business Video/",
            "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video/", "Android/media/com.whatsapp.w4b/WhatsApp Business/Media/WhatsApp Business Video/"),
        GallerySourceKind.SCREENSHOTS to listOf("Movies/Screen recordings/", "Movies/ScreenRecorder/", "DCIM/Screen recordings/"),
        GallerySourceKind.DOWNLOADS to listOf("Download/", "Downloads/"))
    private val videoLabels = labels + mapOf(GallerySourceKind.WHATSAPP_RECEIVED to listOf("WhatsApp Video", "WhatsApp Business Video"),
        GallerySourceKind.SCREENSHOTS to listOf("Screen recordings", "ScreenRecorder"))
    fun selectors(kinds: Set<GallerySourceKind>, modern: Boolean, mediaType: GalleryMediaType = GalleryMediaType.IMAGES): List<String> = kinds.sortedBy { it.ordinal }
        .flatMap { (if (mediaType == GalleryMediaType.IMAGES) { if (modern) folders else labels }
            else { if (modern) videoFolders else videoLabels }).getValue(it) }.map { it.lowercase(Locale.ROOT) }.distinct()
    fun classify(kinds: Set<GallerySourceKind>, label: String, relativePath: String?, modern: Boolean,
        mediaType: GalleryMediaType = GalleryMediaType.IMAGES): GallerySourceKind? {
        val key = (if (modern) relativePath ?: return null else label).lowercase(Locale.ROOT)
        return kinds.singleOrNull { key in selectors(setOf(it), modern, mediaType) }
    }
}

internal object AndroidGalleryReadPermissions {
    fun observe(context: Context, mediaType: GalleryMediaType = GalleryMediaType.IMAGES): GalleryReadCoverage {
        fun granted(permission: String) = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
        return when {
            Build.VERSION.SDK_INT >= 33 && granted(if (mediaType == GalleryMediaType.IMAGES)
                Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_MEDIA_VIDEO) ->
                    if (mediaType == GalleryMediaType.IMAGES) GalleryReadCoverage.FULL_IMAGES else GalleryReadCoverage.FULL_VIDEOS
            Build.VERSION.SDK_INT >= 34 && granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) -> GalleryReadCoverage.SELECTED_ONLY
            Build.VERSION.SDK_INT <= 32 && granted(Manifest.permission.READ_EXTERNAL_STORAGE) ->
                if (mediaType == GalleryMediaType.IMAGES) GalleryReadCoverage.FULL_IMAGES else GalleryReadCoverage.FULL_VIDEOS
            else -> GalleryReadCoverage.NONE
        }
    }
}

/** Explicitly activated, bounded gallery-index discovery; no recursive filesystem
 * crawl, no photo-content opens/writes, no phone settings panel or permission prompt.
 */
internal class AndroidGalleryAlbumDiscovery(context: Context, private val current: () -> NativeGalleryRequest?,
    private val accessEpoch: () -> String? = { null },
    private val mediaType: GalleryMediaType = GalleryMediaType.IMAGES,
    private val readCoverage: () -> GalleryReadCoverage = { AndroidGalleryReadPermissions.observe(context.applicationContext, mediaType) }) {
    private val app = context.applicationContext
    private val resolver = app.contentResolver

    fun discover(cancellation: CancellationSignal = CancellationSignal()): GalleryAlbumCatalog {
        val request = current() ?: return GalleryAlbumCatalog(GalleryReadCoverage.NONE, emptyList())
        if (request.kinds.isEmpty()) return GalleryAlbumCatalog(GalleryReadCoverage.NONE, emptyList())
        if (request.mediaType != mediaType) throw PhotoFolderScopeError("gallery_media_scope_changed")
        if (!request.receiver.allowed) throw PhotoFolderScopeError("gallery_receiver_not_ready")
        val coverage = readCoverage()
        if (!mediaType.acceptsCoverage(coverage)) throw PhotoFolderScopeError("gallery_media_permission_mismatch")
        if (coverage == GalleryReadCoverage.NONE) return GalleryAlbumCatalog(coverage, emptyList(), request)
        val permissionEpoch = accessEpoch()
        if (permissionEpoch != null && !Regex("[0-9a-f]{64}").matches(permissionEpoch)) throw PhotoFolderScopeError("gallery_invalid_access_epoch")
        val started = SystemClock.elapsedRealtime()
        fun fresh() {
            cancellation.throwIfCanceled()
            val now = current()
            if (now == null || !now.receiver.allowed || now.policyEpoch != request.policyEpoch || now.mediaIntent !== request.mediaIntent || now.kinds != request.kinds || now.mediaType != mediaType ||
                now.receiver.owner !== request.receiver.owner || now.receiver.peerId != request.receiver.peerId ||
                 now.receiver.identitySha256 != request.receiver.identitySha256 || now.receiver.permissionEpoch != request.receiver.permissionEpoch ||
                 now.receiver.pairingEpoch != request.receiver.pairingEpoch ||
                 readCoverage() != coverage || accessEpoch() != permissionEpoch) throw PhotoFolderScopeError("gallery_source_scope_changed")
            if (SystemClock.elapsedRealtime() - started > MAX_ELAPSED_MS) throw PhotoFolderScopeError("gallery_discovery_deadline")
        }
        fresh()
        val modern = Build.VERSION.SDK_INT >= 29
        val volumes = if (modern) MediaStore.getExternalVolumeNames(app).toList().sorted() else listOf("external")
        if (volumes.size > MAX_VOLUMES || volumes.any { !Regex("[A-Za-z0-9_-]{1,128}").matches(it) })
            throw PhotoFolderScopeError("gallery_volume_limit")
        val albums = linkedMapOf<Pair<String, String>, GalleryAlbumCandidate>()
        var visited = 0
        var pages = 0
        for (volume in volumes) {
            fresh()
            val collection = mediaType.collection(volume, modern)
            val selectors = GallerySourceRules.selectors(request.kinds, modern, mediaType)
            val filterColumn = if (modern) "relative_path" else "bucket_display_name"
            val projection = arrayOf("_id", "bucket_id", "bucket_display_name", "mime_type") + if (modern) arrayOf("relative_path") else emptyArray()
            var after = 0L
            while (true) {
                fresh()
                if (++pages > MAX_PAGES) throw PhotoFolderScopeError("gallery_page_limit")
                val args = Bundle().apply {
                    putString(ContentResolver.QUERY_ARG_SQL_SELECTION, "_id > ? AND LOWER($filterColumn) IN (${selectors.joinToString(",") { "?" }})")
                    putStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, arrayOf(after.toString(), *selectors.toTypedArray()))
                    putString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER, "_id ASC")
                    putInt(ContentResolver.QUERY_ARG_LIMIT, PAGE_SIZE)
                }
                val cursor = resolver.query(collection, projection, args, cancellation)
                    ?: throw PhotoFolderScopeError("gallery_provider_unavailable")
                var count = 0
                cursor.use {
                    val idColumn = it.getColumnIndexOrThrow("_id"); val bucketColumn = it.getColumnIndexOrThrow("bucket_id")
                    val nameColumn = it.getColumnIndexOrThrow("bucket_display_name"); val mimeColumn = it.getColumnIndexOrThrow("mime_type")
                    val pathColumn = if (modern) it.getColumnIndexOrThrow("relative_path") else -1
                    while (true) {
                        fresh()
                        if (!it.moveToNext()) break
                        fresh()
                        if (++count > PAGE_SIZE || ++visited > MAX_ROWS) throw PhotoFolderScopeError("gallery_provider_page_limit")
                        if (it.getType(idColumn) != Cursor.FIELD_TYPE_INTEGER || it.getLong(idColumn) <= after)
                            throw PhotoFolderScopeError("gallery_invalid_page_order")
                        after = it.getLong(idColumn)
                        if (it.isNull(bucketColumn) || it.getType(nameColumn) != Cursor.FIELD_TYPE_STRING || it.getType(mimeColumn) != Cursor.FIELD_TYPE_STRING)
                            throw PhotoFolderScopeError("gallery_invalid_album_metadata")
                        val bucket = it.getString(bucketColumn)
                        val label = it.getString(nameColumn)
                        val path = if (modern && !it.isNull(pathColumn)) it.getString(pathColumn) else null
                        if (!Regex("[A-Za-z0-9_-]{1,128}").matches(bucket) || label.length !in 1..256 ||
                            label.any { character -> character.code < 32 || character.code == 127 } || path != null && path.length > 4096)
                            throw PhotoFolderScopeError("gallery_invalid_album_metadata")
                        if (!mediaType.acceptsMime(it.getString(mimeColumn))) continue
                        val kind = GallerySourceRules.classify(request.kinds, label, path, modern, mediaType) ?: continue
                        val key = volume to bucket
                        val previous = albums[key]
                        if (previous != null && (previous.kind != kind || previous.displayName != label || previous.relativePath != path))
                            throw PhotoFolderScopeError("gallery_ambiguous_bucket")
                        if (previous == null && albums.size >= MAX_ALBUMS) throw PhotoFolderScopeError("gallery_album_limit")
                        albums[key] = GalleryAlbumCandidate(kind, volume, bucket, label, path, (previous?.visibleImageCount ?: 0L) + 1, false)
                    }
                }
                fresh()
                if (count < PAGE_SIZE) break
            }
        }
        fresh()
        if (modern && MediaStore.getExternalVolumeNames(app).toList().sorted() != volumes)
            throw PhotoFolderScopeError("gallery_volumes_changed")
        val candidates = albums.values.map { candidate ->
            // On legacy Android a display label is not enough to disambiguate
            // several albums with that same name. Let the desktop select one.
            candidate.copy(needsAlbumChoice = !modern && albums.values.count {
                it.kind == candidate.kind && it.displayName.equals(candidate.displayName, ignoreCase = true) } > 1)
        }
        fresh()
        return GalleryAlbumCatalog(coverage, candidates, request, permissionEpoch)
    }
    companion object {
        const val PAGE_SIZE = 256
        const val MAX_ROWS = 50_000
        const val MAX_ALBUMS = 128
        const val MAX_VOLUMES = 8
        const val MAX_PAGES = 208
        const val MAX_ELAPSED_MS = 30_000L
    }
}
