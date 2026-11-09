package io.gitlab.maik3531.magnolienotes.telefon

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaDataSource
import android.media.MediaMetadataRetriever
import android.os.Build
import android.os.CancellationSignal

/** Ephemeral raster only. No URI, provider access, file copy or mutation permit. */
internal object NativeGalleryRecoveryPreview {
    const val MAX_BYTES = 16 * 1024 * 1024

    fun read(archive: NativeGalleryTrashArchive, entry: NativeGalleryArchiveEntry,
        permit: NativeGalleryTrashBookPermit, side: Int, cancellation: CancellationSignal,
        current: () -> Unit): Bitmap {
        fun active() { cancellation.throwIfCanceled(); permit.requireCurrent(); current() }
        active()
        if (side !in setOf(192, 1024) || entry.bytes !in 1..MAX_BYTES.toLong())
            throw PhotoFolderScopeError("gallery_preview_bound")
        val origin = archive.verifiedOrigin(entry, permit)
        val bytes = ByteArray(entry.bytes.toInt())
        var offset = 0
        var result: Bitmap? = null
        try {
            archive.readContent(entry, permit) { chunk ->
                active()
                if (offset + chunk.size > bytes.size) throw PhotoFolderScopeError("gallery_preview_bound")
                chunk.copyInto(bytes, offset); offset += chunk.size
            }
            active()
            if (offset != bytes.size) throw PhotoFolderScopeError("gallery_preview_short_read")
            result = decode(bytes, origin.string("media_type"), side, ::active)
            archive.verifyContent(entry, permit); active()
            return result
        } catch (error: Throwable) { result?.recycle(); throw error }
        finally { bytes.fill(0) }
    }

    internal fun decode(bytes: ByteArray, kind: String, side: Int, current: () -> Unit): Bitmap {
        current()
        if (bytes.isEmpty() || bytes.size > MAX_BYTES || side !in setOf(192, 1024))
            throw PhotoFolderScopeError("gallery_preview_bound")
        var bitmap: Bitmap? = null
        try {
            bitmap = when (kind) {
                "images" -> {
                    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                    dimensions(bounds.outWidth, bounds.outHeight)
                    if (bounds.outMimeType !in setOf("image/png", "image/jpeg", "image/webp"))
                        throw PhotoFolderScopeError("gallery_preview_format")
                    var sample = 1
                    while (maxOf(bounds.outWidth, bounds.outHeight) / sample > side * 2) sample *= 2
                    current()
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
                }
                "video" -> {
                    if (Build.VERSION.SDK_INT < 27) throw PhotoFolderScopeError("gallery_preview_decoder_unavailable")
                    MediaMetadataRetriever().use { decoder ->
                        val source = object : MediaDataSource() {
                            override fun getSize() = bytes.size.toLong()
                            override fun close() { }
                            override fun readAt(position: Long, buffer: ByteArray, offset: Int, size: Int): Int {
                                current()
                                if (position < 0 || offset < 0 || size < 0 || offset > buffer.size - size)
                                    throw PhotoFolderScopeError("gallery_preview_bound")
                                if (position >= bytes.size) return -1
                                val count = minOf(size, bytes.size - position.toInt())
                                bytes.copyInto(buffer, offset, position.toInt(), position.toInt() + count)
                                return count
                            }
                        }
                        decoder.setDataSource(source)
                        val width = decoder.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() ?: 0
                        val height = decoder.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull() ?: 0
                        dimensions(width, height); current()
                        val scale = minOf(1.0, side.toDouble() / maxOf(width, height))
                        decoder.getScaledFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST_SYNC,
                            maxOf(1, (width * scale).toInt()), maxOf(1, (height * scale).toInt()))
                    }
                }
                else -> throw PhotoFolderScopeError("gallery_preview_format")
            } ?: throw PhotoFolderScopeError("gallery_preview_decode_failed")
            current()
            if (maxOf(bitmap.width, bitmap.height) > side) {
                val scale = side.toDouble() / maxOf(bitmap.width, bitmap.height)
                val scaled = Bitmap.createScaledBitmap(bitmap, maxOf(1, (bitmap.width * scale).toInt()),
                    maxOf(1, (bitmap.height * scale).toInt()), true)
                if (scaled !== bitmap) bitmap.recycle()
                bitmap = scaled
            }
            current(); return bitmap
        } catch (error: Throwable) { bitmap?.recycle(); throw error }
    }

    private fun dimensions(width: Int, height: Int) {
        if (width !in 1..32768 || height !in 1..32768 || width.toLong() * height > 24_000_000)
            throw PhotoFolderScopeError("gallery_preview_dimensions")
    }
}
