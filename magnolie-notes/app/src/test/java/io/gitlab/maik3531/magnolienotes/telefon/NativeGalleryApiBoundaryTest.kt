package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.graphics.Bitmap
import android.media.MediaDataSource
import android.media.MediaMetadataRetriever
import android.os.ParcelFileDescriptor
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.annotation.Resetter
import java.io.File
import java.io.FileDescriptor

/** Synthetic decoder only: verifies API boundaries/cleanup, not native media decoding. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class, shadows = [NativeGalleryApiBoundaryTest.PreviewDecoder::class])
class NativeGalleryApiBoundaryTest {
    @Before fun resetDecoderFixture() { PreviewDecoder.reset() }

    @Implements(MediaMetadataRetriever::class)
    class PreviewDecoder {
        @Implementation fun __constructor__() { }
        @Implementation fun setDataSource(source: MediaDataSource) {
            check(source.size == 1L)
        }
        @Implementation fun extractMetadata(key: Int): String? = if (invalidMetadata) null else when (key) {
            MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH -> "16"
            MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT -> "9"
            else -> null
        }
        @Implementation fun getScaledFrameAtTime(timeUs: Long, option: Int, width: Int, height: Int): Bitmap {
            check(timeUs == 0L && option == MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
            return Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        }
        @Implementation fun release() { releases++ }
        companion object {
            var releases = 0
            var invalidMetadata = false
            @JvmStatic @Resetter fun reset() { releases = 0; invalidMetadata = false }
        }
    }

    @Test @Config(sdk = [26]) fun api26InspectionRejectsBeforeDescriptorOrOwnerAccess() {
        var ownerCalled = false
        val error = assertThrows(PhotoFolderScopeError::class.java) {
            NativeIncomingMediaInspection.inspect(FileDescriptor(), 1, GalleryMediaType.IMAGES, "image/png") { ownerCalled = true }
        }
        assertEquals("gallery_incoming_media_api27_required", error.message)
        assertFalse(ownerCalled)
    }

    @Test @Config(sdk = [26]) fun api26WriteWitnessRejectsInsteadOfReducingTimestampPrecision() {
        val file = File.createTempFile("gallery-api26-", ".bin", File("/tmp/opencode"))
        try {
            ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY).use { descriptor ->
                val error = assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryPcWriteTarget.witness(descriptor) }
                assertEquals("gallery_pc_write_target_changed", error.message)
            }
        } finally { file.delete() }
    }

    @Test fun api28VideoPreviewReleasesDecoderWithoutApi29AutoCloseable() {
        val bitmap = NativeGalleryRecoveryPreview.decode(byteArrayOf(1), "video", 192) { }
        try { assertEquals(16, bitmap.width); assertEquals(9, bitmap.height) }
        finally { bitmap.recycle() }
        assertEquals(1, PreviewDecoder.releases)
    }

    @Test fun api28VideoPreviewAlsoReleasesDecoderWhenMetadataIsRejected() {
        PreviewDecoder.invalidMetadata = true
        assertThrows(PhotoFolderScopeError::class.java) {
            NativeGalleryRecoveryPreview.decode(byteArrayOf(1), "video", 192) { }
        }
        assertEquals(1, PreviewDecoder.releases)
    }
}
