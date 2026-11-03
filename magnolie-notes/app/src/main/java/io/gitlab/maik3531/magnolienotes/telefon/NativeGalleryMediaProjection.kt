package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Same frozen associations and classification for normal and renewed native
 * sources. Neither a source scan nor destination/reconciliation authority. */
internal object NativeGalleryMediaProjection {
    fun page(snapshot: ProtectedPhotoSourceSnapshot, lease: NativePhotoSourceLease, after: Int,
        read: (String, Int) -> ByteArray, ensureNative: () -> Unit): JsonObject {
        if (lease !is GalleryPhotoSourceLease) DeviceFileControl.fail("gallery_media_native_scope_required")
        ensureNative()
        val manifest = snapshot.manifest
        val origins = snapshot.galleryOrigins ?: DeviceFileControl.fail("gallery_media_origins_required")
        if (after !in 0..manifest.files.size) DeviceFileControl.fail("gallery_media_invalid_cursor")
        val end = minOf(after + 8, manifest.files.size)
        val entries = (after until end).map { offset ->
            ensureNative()
            val file = manifest.files[offset]; val origin = origins.entries[offset]
            if (origin.fileId != file.id) DeviceFileControl.fail("gallery_media_origins_changed")
            val kind = if (lease.activation.mediaType == GalleryMediaType.VIDEO) "video" else {
                val observed = NativeImageAnimation.inspect(manifest, file.id) { index -> ensureNative(); read(file.id, index) }
                ensureNative()
                when (observed.kind) {
                    NativeImageAnimationKind.ANIMATED -> "animation"
                    NativeImageAnimationKind.STILL -> "image"
                    NativeImageAnimationKind.UNKNOWN -> "unknown_image"
                }
            }
            JsonObject(mapOf("file_id" to JsonPrimitive(file.id), "photo_id" to JsonPrimitive(origin.photoId), "media_kind" to JsonPrimitive(kind)))
        }
        val epoch = DeviceFileControl.digest("magnolie-gallery-media-namespace-v1\u0000", JsonObject(mapOf(
            "sender_id" to JsonPrimitive(manifest.senderId), "source_key" to JsonPrimitive(lease.sourceKey),
            "media_namespace" to JsonPrimitive(lease.access.mediaStoreVersion ?: "runtime:" + lease.readGrantToken))))
        ensureNative()
        return JsonObject(mapOf("format" to JsonPrimitive(1), "manifest_sha256" to JsonPrimitive(manifest.fingerprint),
            "source_epoch" to JsonPrimitive(epoch), "media_type" to JsonPrimitive(lease.activation.mediaType.uriSegment),
            "insertion_witness" to JsonPrimitive(origins.hasNativeInsertionWitness), "after" to JsonPrimitive(after),
            "next_cursor" to (if (end < manifest.files.size) JsonPrimitive(end) else JsonNull),
            "total_files" to JsonPrimitive(manifest.files.size), "entries" to JsonArray(entries))).also {
            if (TelefonKanonisch.bytes(it).size > DeviceFileControl.MAX_WIRE_BYTES - 2048) DeviceFileControl.fail("gallery_media_page_budget")
        }
    }
}
