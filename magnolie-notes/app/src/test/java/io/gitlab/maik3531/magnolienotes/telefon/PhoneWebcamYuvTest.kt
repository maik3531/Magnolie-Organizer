package io.gitlab.maik3531.magnolienotes.telefon

import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class PhoneWebcamYuvTest {
    @Test fun paddedInterleavedChromaAndBufferOffsetsProduceExactI420WithoutChangingSources() {
        val y = ByteBuffer.wrap(ByteArray(648 * 480 + 5) { 17 }).apply { position(5) }
        val u = ByteBuffer.wrap(ByteArray(648 * 240 + 7) { if (it % 2 == 1) 34 else 99 }).apply { position(7) }
        val v = ByteBuffer.wrap(ByteArray(648 * 240 + 8) { if (it % 2 == 0) 51 else 99 }).apply { position(8) }
        val data = PhoneWebcamYuv.i420(640, 480, listOf(PhoneWebcamYuv.Plane(y, 648, 1),
            PhoneWebcamYuv.Plane(u, 648, 2), PhoneWebcamYuv.Plane(v, 648, 2)))
        assertEquals(460800, data.size)
        assertArrayEquals(ByteArray(640 * 480) { 17 }, data.copyOfRange(0, 640 * 480))
        assertArrayEquals(ByteArray(320 * 240) { 34 }, data.copyOfRange(640 * 480, 640 * 480 + 320 * 240))
        assertArrayEquals(ByteArray(320 * 240) { 51 }, data.copyOfRange(640 * 480 + 320 * 240, data.size))
        assertEquals(5, y.position()); assertEquals(7, u.position()); assertEquals(8, v.position())
    }

    @Test fun missingBytesMalformedStrideOrUnnegotiatedResolutionFailBeforeSourceReads() {
        val valid = PhoneWebcamYuv.Plane(ByteBuffer.allocate(640 * 480), 640, 1)
        for (bad in listOf(PhoneWebcamYuv.Plane(ByteBuffer.allocate(1), 640, 1),
            PhoneWebcamYuv.Plane(ByteBuffer.allocate(640 * 480), -1, 1),
            PhoneWebcamYuv.Plane(ByteBuffer.allocate(640 * 480), 640, Int.MAX_VALUE))) {
            assertThrows(IllegalArgumentException::class.java) { PhoneWebcamYuv.i420(640, 480, listOf(bad, valid, valid)) }
        }
        assertThrows(IllegalArgumentException::class.java) { PhoneWebcamYuv.i420(1920, 1080, listOf(valid, valid, valid)) }
    }
}
