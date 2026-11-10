package io.gitlab.maik3531.magnolienotes.telefon

import java.nio.ByteBuffer

/** Exact bounded YUV_420_888 planes → negotiated I420, including padded/interleaved
 * chroma. Original buffers/positions are never changed or retained by the result.
 */
internal object PhoneWebcamYuv {
    data class Plane(val bytes: ByteBuffer, val rowStride: Int, val pixelStride: Int)
    fun i420(width: Int, height: Int, planes: List<Plane>): ByteArray {
        require(width == PhoneWebcamMediaCodec.WIDTH && height == PhoneWebcamMediaCodec.HEIGHT && planes.size == 3) {
            "webcam_native_image_format_unsupported"
        }
        val output = ByteArray(PhoneWebcamMediaCodec.VIDEO_BYTES)
        var at = 0
        for ((index, plane) in planes.withIndex()) {
            val columns = if (index == 0) width else width / 2
            val rows = if (index == 0) height else height / 2
            val buffer = plane.bytes.duplicate()
            val start = buffer.position().toLong()
            require(plane.pixelStride in 1..2 && plane.rowStride.toLong() >= (columns - 1L) * plane.pixelStride + 1 &&
                start + (rows - 1L) * plane.rowStride + (columns - 1L) * plane.pixelStride < buffer.limit()) {
                "webcam_native_image_plane_invalid"
            }
            for (row in 0 until rows) for (column in 0 until columns) {
                output[at++] = buffer.get((start + row.toLong() * plane.rowStride + column.toLong() * plane.pixelStride).toInt())
            }
        }
        return output
    }
}
