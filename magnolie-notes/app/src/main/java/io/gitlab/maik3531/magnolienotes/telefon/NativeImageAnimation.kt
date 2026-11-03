package io.gitlab.maik3531.magnolienotes.telefon

import java.security.MessageDigest
import java.util.Locale

internal enum class NativeImageAnimationKind { STILL, ANIMATED, UNKNOWN }

/** A byte-bound observation, not a mutation right, target mapping or receipt. */
internal data class NativeImageAnimationObservation(val manifestSha256: String, val fileId: String,
    val contentSha256: String, val size: Long, val kind: NativeImageAnimationKind) {
    val grantsWriteAuthority: Boolean get() = false
    val isSavedReceipt: Boolean get() = false
}

/** Bounded GIF container inspection, with no pixel/LZW decompression. Unknown or
 * malformed containers stay unknown, never guessed to be a video. Other image
 * animation formats require separate bounded parsers; filename is not evidence. */
internal object NativeImageAnimation {
    private const val MAX_BLOCKS = 100_000
    private class InvalidGif : RuntimeException()

    fun inspect(manifest: DeviceFileManifest, fileId: String, readChunk: (Int) -> ByteArray): NativeImageAnimationObservation {
        val file = manifest.files.singleOrNull { it.id == fileId } ?: DeviceFileControl.fail("image_animation_unknown_member")
        val chunks = ((file.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
        fun chunk(index: Int): ByteArray {
            val data = readChunk(index)
            val expected = minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), file.size - index.toLong() * DeviceFileManifest.CHUNK_BYTES).toInt()
            if (index !in 0 until chunks || data.size != expected) {
                data.fill(0); DeviceFileControl.fail("image_animation_source_chunk_changed")
            }
            return data
        }
        val digest = MessageDigest.getInstance("SHA-256")
        for (index in 0 until chunks) {
            val data = chunk(index)
            try { digest.update(data) } finally { data.fill(0) }
        }
        val actual = digest.digest().joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        if (actual != file.sha256) DeviceFileControl.fail("image_animation_source_hash_changed")
        val kind = Reader(file.size, ::chunk).use { input ->
            try { gif(input) } catch (_: InvalidGif) { NativeImageAnimationKind.UNKNOWN }
        }
        return NativeImageAnimationObservation(manifest.fingerprint, file.id, actual, file.size, kind)
    }

    private class Reader(val size: Long, private val chunk: (Int) -> ByteArray) : AutoCloseable {
        var position = 0L
        private var index = -1
        private var data = ByteArray(0)
        fun byte(): Int {
            if (position >= size) throw InvalidGif()
            val wanted = (position / DeviceFileManifest.CHUNK_BYTES).toInt()
            if (wanted != index) { data.fill(0); data = chunk(wanted); index = wanted }
            return (data[(position++ % DeviceFileManifest.CHUNK_BYTES).toInt()].toInt() and 255)
        }
        fun skip(count: Long) {
            if (count < 0 || count > size - position) throw InvalidGif()
            position += count
        }
        fun word() = byte() or (byte() shl 8)
        override fun close() { data.fill(0) }
    }

    private fun gif(input: Reader): NativeImageAnimationKind {
        val header = CharArray(6) { input.byte().toChar() }.concatToString()
        if (header != "GIF87a" && header != "GIF89a") return NativeImageAnimationKind.UNKNOWN
        if (input.word() == 0 || input.word() == 0) throw InvalidGif()
        val packed = input.byte(); input.skip(2)
        if (packed and 128 != 0) input.skip(3L * (1 shl ((packed and 7) + 1)))
        var blocks = 0; var frames = 0
        fun subBlocks(): Long {
            var bytes = 0L
            while (true) {
                if (++blocks > MAX_BLOCKS) throw InvalidGif()
                val count = input.byte()
                if (count == 0) return bytes
                input.skip(count.toLong()); bytes += count
            }
        }
        while (++blocks <= MAX_BLOCKS) {
            when (input.byte()) {
                0x3B -> return if (input.position == input.size && frames > 0)
                    (if (frames > 1) NativeImageAnimationKind.ANIMATED else NativeImageAnimationKind.STILL)
                    else NativeImageAnimationKind.UNKNOWN
                0x21 -> {
                    if (input.byte() == 0xF9) {
                        if (input.byte() != 4) throw InvalidGif()
                        input.skip(4)
                        if (input.byte() != 0) throw InvalidGif()
                    } else subBlocks()
                }
                0x2C -> {
                    input.skip(4)
                    if (input.word() == 0 || input.word() == 0) throw InvalidGif()
                    val flags = input.byte()
                    if (flags and 128 != 0) input.skip(3L * (1 shl ((flags and 7) + 1)))
                    if (input.byte() !in 2..8 || subBlocks() == 0L) throw InvalidGif()
                    frames++
                }
                else -> throw InvalidGif()
            }
        }
        return NativeImageAnimationKind.UNKNOWN
    }
}
