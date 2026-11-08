package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import java.io.ByteArrayInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class CameraPhotoMetadataTest {
    companion object {
        /** A JPEG APP1 with real TIFF Make and DateTimeOriginal tags. */
        internal fun photograph(): ByteArray {
            val tiff = ByteBuffer.allocate(82).order(ByteOrder.LITTLE_ENDIAN)
            tiff.put('I'.code.toByte()).put('I'.code.toByte()).putShort(42).putInt(8)
            tiff.putShort(2)
            tiff.putShort(0x010f).putShort(2).putInt(6).putInt(38)
            tiff.putShort(0x8769.toShort()).putShort(4).putInt(1).putInt(44)
            tiff.putInt(0).put("Phone\u0000".toByteArray())
            tiff.putShort(1).putShort(0x9003.toShort()).putShort(2).putInt(20).putInt(62).putInt(0)
            tiff.put("2026:11:08 13:14:15\u0000".toByteArray())
            return byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 0xe1.toByte(), 0, 90) +
                "Exif\u0000\u0000".toByteArray() + tiff.array() + byteArrayOf(0xff.toByte(), 0xd9.toByte())
        }
    }

    @Test fun nativeExifReaderUsesCaptureMetadataNotNamesOrPlainText() {
        assertTrue(CameraPhotoMetadata.matches(ByteArrayInputStream(photograph())))
        assertFalse(CameraPhotoMetadata.matches(ByteArrayInputStream("DCIM/Camera/IMG_1234.jpg Phone 2026:11:08".toByteArray())))
        assertFalse(CameraPhotoMetadata.matches(ByteArrayInputStream(byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 0xd9.toByte()))))
    }

    @Test fun unknownMalformedAndNonCaptureAttributesAreExcluded() {
        assertTrue(CameraPhotoMetadata.matchesAttributes("Phone", null, "2024:02:29 12:00:00"))
        assertTrue(CameraPhotoMetadata.matchesAttributes(null, "Camera model", "2026:11:08 12:00:00"))
        for (taken in listOf(null, "", "2026:02:29 12:00:00", "0000:00:00 00:00:00", "2026:11:08", "2026:11:08 25:00:00"))
            assertFalse(CameraPhotoMetadata.matchesAttributes("Phone", "Camera", taken))
        assertFalse(CameraPhotoMetadata.matchesAttributes(null, null, "2026:11:08 12:00:00"))
        assertFalse(CameraPhotoMetadata.matchesAttributes(" ", "\n", "2026:11:08 12:00:00"))
    }
}
