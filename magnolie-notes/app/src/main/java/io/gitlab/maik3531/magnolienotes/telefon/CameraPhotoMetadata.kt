package io.gitlab.maik3531.magnolienotes.telefon

import android.media.ExifInterface
import java.io.FilterInputStream
import java.io.IOException
import java.io.InputStream
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.time.format.ResolverStyle

/** A metadata selection criterion, not proof of camera provenance. Names,
 * extensions, directory names and file modification times are not evidence.
 * Missing/stripped/unsupported metadata does not satisfy the optional filter. */
internal object CameraPhotoMetadata {
    private val timestamp = DateTimeFormatter.ofPattern("uuuu:MM:dd HH:mm:ss").withResolverStyle(ResolverStyle.STRICT)
    internal const val MAX_METADATA_BYTES = 1024 * 1024

    fun matches(input: InputStream): Boolean {
        // Do not let EXIF discovery scan an unbounded media file. The caller
        // owns and closes its original native, cancellation-aware READ stream.
        val bounded = object : FilterInputStream(input) {
            var remaining = MAX_METADATA_BYTES
            override fun read(): Int {
                if (remaining <= 0) throw IOException("camera_metadata_limit")
                return `in`.read().also { if (it >= 0) remaining-- }
            }
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                if (length == 0) return 0
                if (remaining <= 0) throw IOException("camera_metadata_limit")
                return `in`.read(buffer, offset, minOf(length, remaining)).also { if (it > 0) remaining -= it }
            }
            override fun skip(count: Long): Long {
                if (count <= 0) return 0
                if (remaining <= 0) throw IOException("camera_metadata_limit")
                return `in`.skip(minOf(count, remaining.toLong())).also { remaining -= it.toInt() }
            }
            override fun markSupported() = false
        }
        return try {
            val exif = ExifInterface(bounded)
            matchesAttributes(exif.getAttribute(ExifInterface.TAG_MAKE), exif.getAttribute(ExifInterface.TAG_MODEL),
                exif.getAttribute(ExifInterface.TAG_DATETIME_ORIGINAL))
        } catch (_: IOException) { false }
    }

    internal fun matchesAttributes(make: String?, model: String?, taken: String?): Boolean {
        fun device(value: String?) = value != null && value.trim().length in 1..128 && value.none { it.isISOControl() }
        if (!device(make) && !device(model)) return false
        if (taken == null || !Regex("[0-9]{4}:[0-9]{2}:[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}").matches(taken)) return false
        return runCatching { LocalDateTime.parse(taken, timestamp).year in 1900..9999 }.getOrDefault(false)
    }
}
