package io.gitlab.maik3531.magnolienotes.telefon

import android.graphics.BitmapFactory
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.os.Looper
import android.system.Os
import android.system.OsConstants
import java.io.FileDescriptor

/** Read-only native metadata, not a Saved receipt or publication permission.
 * No pixels/frames are decoded, no JPEG/MP4 conversion or re-encoding occurs. */
internal data class NativeIncomingMediaObservation internal constructor(val mediaType: GalleryMediaType,
    val mimeType: String, val width: Int, val height: Int, val durationMs: Long?) {
    internal val grantsWriteAuthority: Boolean get() = false
    internal val isSavedReceipt: Boolean get() = false
}

/** Platform parser admission of an already hash-verified original descriptor.
 * A name, remote MIME claim, stored copy_verified flag or hash alone is not
 * evidence that Android actually recognizes the requested media kind. */
internal object NativeIncomingMediaInspection {
    internal fun inspect(descriptor: FileDescriptor, bytes: Long, kind: GalleryMediaType, mimeType: String,
        ensureNative: () -> Unit): NativeIncomingMediaObservation {
        if (Looper.myLooper() == Looper.getMainLooper() || bytes !in 1..DeviceFileManifest.MAX_FILE_BYTES)
            fail("gallery_incoming_media_io_required")
        ensureNative()
        val before = Os.fstat(descriptor)
        if (!OsConstants.S_ISREG(before.st_mode) || before.st_size != bytes) fail("gallery_incoming_media_descriptor_changed")
        Os.lseek(descriptor, 0, OsConstants.SEEK_SET)
        val result = if (kind == GalleryMediaType.IMAGES) {
            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            val bitmap = BitmapFactory.decodeFileDescriptor(descriptor, null, options)
            bitmap?.recycle()
            ensureNative()
            if (bitmap != null || options.outMimeType != mimeType || !mimeType.startsWith("image/"))
                fail("gallery_incoming_image_not_recognized")
            dimensions(options.outWidth, options.outHeight)
            NativeIncomingMediaObservation(kind, mimeType, options.outWidth, options.outHeight, null)
        } else {
            val metadata = MediaMetadataRetriever()
            try {
                metadata.setDataSource(descriptor, 0, bytes); ensureNative()
                if (!mimeType.startsWith("video/") || metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_MIMETYPE) != mimeType ||
                    metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_VIDEO) != "yes")
                    fail("gallery_incoming_video_not_recognized")
                val width = metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull()
                    ?: fail("gallery_incoming_video_not_recognized")
                val height = metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull()
                    ?: fail("gallery_incoming_video_not_recognized")
                val duration = metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()
                    ?.takeIf { it > 0 } ?: fail("gallery_incoming_video_not_recognized")
                dimensions(width, height)
                val extractor = MediaExtractor()
                try {
                    extractor.setDataSource(descriptor, 0, bytes); ensureNative()
                    if (extractor.trackCount !in 1..16) fail("gallery_incoming_video_tracks_invalid")
                    var video = false
                    for (track in 0 until extractor.trackCount) {
                        ensureNative()
                        val format = extractor.getTrackFormat(track)
                        val mime = format.getString(MediaFormat.KEY_MIME) ?: fail("gallery_incoming_video_tracks_invalid")
                        if (mime.startsWith("video/")) {
                            dimensions(format.getInteger(MediaFormat.KEY_WIDTH), format.getInteger(MediaFormat.KEY_HEIGHT)); video = true
                        }
                    }
                    if (!video) fail("gallery_incoming_video_tracks_invalid")
                } finally { extractor.release() }
                NativeIncomingMediaObservation(kind, mimeType, width, height, duration)
            } finally { metadata.release() }
        }
        ensureNative()
        val after = Os.fstat(descriptor)
        if (before.st_dev != after.st_dev || before.st_ino != after.st_ino || before.st_size != after.st_size ||
            before.st_mtim != after.st_mtim || before.st_ctim != after.st_ctim)
            fail("gallery_incoming_media_descriptor_changed")
        return result
    }

    private fun dimensions(width: Int, height: Int) {
        // Metadata only, but absurd/missing dimensions are not admitted. This
        // bound does not allocate a pixel buffer or manufacture camera origin.
        if (width !in 1..1_000_000 || height !in 1..1_000_000 || width.toLong() * height > 1_000_000_000)
            fail("gallery_incoming_media_dimensions_invalid")
    }
    private fun fail(code: String): Nothing = DeviceFileControl.fail(code)
}
