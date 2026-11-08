package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.graphics.Bitmap
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.os.ParcelFileDescriptor
import android.system.StructStat
import android.system.StructTimespec
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.annotation.Implements
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Resetter
import org.robolectric.shadows.ShadowLinux
import org.robolectric.shadows.ShadowMediaExtractor
import org.robolectric.shadows.ShadowMediaMetadataRetriever
import org.robolectric.shadows.util.DataSource
import java.io.File
import java.io.FileDescriptor
import java.io.FileInputStream
import java.nio.file.Files
import java.nio.file.attribute.FileTime
import java.util.concurrent.Callable
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [NativeIncomingMediaInspectionTest.FixtureLinux::class])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class NativeIncomingMediaInspectionTest {
    /** Robolectric's stock fstat(fd) delegates to stat(null), not the held
     * fixture. Supply actual host fixture attributes ONLY for registered FDs;
     * this is not physical Android syscall acceptance or a product bypass. */
    @Implements(className = "libcore.io.Linux", isInAndroidSdk = false)
    class FixtureLinux : ShadowLinux() {
        @Implementation override fun fstat(fd: FileDescriptor): StructStat {
            val file = files[fd] ?: return super.fstat(fd)
            val a = Files.readAttributes(file.toPath(), "unix:dev,ino,mode,size,nlink,uid,gid,rdev,lastAccessTime,lastModifiedTime,ctime")
            fun number(name: String) = (a.getValue(name) as Number).toLong()
            fun time(name: String): StructTimespec {
                val instant = (a.getValue(name) as FileTime).toInstant()
                return StructTimespec(instant.epochSecond, instant.nano.toLong())
            }
            return StructStat(number("dev"), number("ino"), number("mode").toInt(), number("nlink"), number("uid").toInt(),
                number("gid").toInt(), number("rdev"), number("size"), time("lastAccessTime"), time("lastModifiedTime"), time("ctime"), 4096, 1)
        }
        @Implementation fun lseek(fd: FileDescriptor, offset: Long, whence: Int): Long {
            check(whence == android.system.OsConstants.SEEK_SET && files.containsKey(fd))
            return streams.getOrPut(fd) { FileInputStream(fd) }.channel.position(offset).position()
        }
        companion object {
            val files = java.util.concurrent.ConcurrentHashMap<FileDescriptor, File>()
            private val streams = java.util.concurrent.ConcurrentHashMap<FileDescriptor, FileInputStream>()
            @JvmStatic @Resetter fun reset() {
                streams.values.forEach { it.close() }; streams.clear(); files.clear()
            }
        }
    }
    private fun readOnly(file: File) = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY).also {
        FixtureLinux.files[it.fileDescriptor] = file
    }
    private fun <T> fixture(action: (File, (() -> T) -> T) -> T): T {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "incoming-native-media338-").toFile()
        val executor = Executors.newSingleThreadExecutor()
        fun io(work: () -> T): T = try { executor.submit(Callable { work() }).get(15, TimeUnit.SECONDS) }
            catch (error: ExecutionException) { throw error.cause ?: error }
        try { return action(root, ::io) }
        finally { executor.shutdownNow(); check(executor.awaitTermination(5, TimeUnit.SECONDS)); root.deleteRecursively() }
    }

    @Test fun actualNativeImageBoundsRecognizeOriginalPngAndJpegWithoutChangingBytesOrAllocatingPixels() = fixture<Unit> { root, io ->
        for ((format, mime) in listOf(Bitmap.CompressFormat.PNG to "image/png", Bitmap.CompressFormat.JPEG to "image/jpeg")) {
            val file = File(root, if (mime == "image/png") "native.png" else "native.jpg")
            val bitmap = Bitmap.createBitmap(16, 9, Bitmap.Config.ARGB_8888)
            try { file.outputStream().use { assertTrue(bitmap.compress(format, 95, it)) } } finally { bitmap.recycle() }
            val before = file.readBytes()
            readOnly(file).use { descriptor ->
                io {
                    val result = NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, file.length(), GalleryMediaType.IMAGES, mime) { }
                    assertEquals(16, result.width); assertEquals(9, result.height); assertEquals(mime, result.mimeType)
                    assertNull(result.durationMs); assertFalse(result.grantsWriteAuthority); assertFalse(result.isSavedReceipt)
                }
            }
            assertArrayEquals(before, file.readBytes())
        }
    }

    @Test fun photoFilterChecksOriginalCaptureTagsBeforeAdmittingIncomingImages() = fixture<Unit> { root, io ->
        for (capture in listOf(false, true)) {
            val file = File(root, if (capture) "capture.txt" else "camera.jpg")
            val bitmap = Bitmap.createBitmap(16, 9, Bitmap.Config.ARGB_8888)
            try { file.outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.JPEG, 95, it)) } } finally { bitmap.recycle() }
            if (capture) {
                val original = file.readBytes(); val metadata = CameraPhotoMetadataTest.photograph()
                file.writeBytes(original.take(2).toByteArray() + metadata.copyOfRange(2, metadata.size - 2) + original.copyOfRange(2, original.size))
            }
            val before = file.readBytes()
            readOnly(file).use { descriptor -> io {
                if (capture) {
                    val observation = NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, file.length(), GalleryMediaType.IMAGES,
                        "image/jpeg", photosOnly = true) { }
                    assertEquals(16, observation.width); assertEquals(9, observation.height)
                } else assertThrows(PhotoFolderScopeError::class.java) {
                    NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, file.length(), GalleryMediaType.IMAGES,
                        "image/jpeg", photosOnly = true) { }
                }
            } }
            assertArrayEquals(before, file.readBytes())
        }
    }

    @Test fun claimedMimeGarbageDescriptorLengthAndUiThreadDoNotManufactureImageAdmission() = fixture<Unit> { root, io ->
        val png = File(root, "image.jpg")
        val bitmap = Bitmap.createBitmap(2, 3, Bitmap.Config.ARGB_8888)
        try { png.outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) } } finally { bitmap.recycle() }
        readOnly(png).use { descriptor ->
            assertThrows(PhotoFolderScopeError::class.java) {
                NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, png.length(), GalleryMediaType.IMAGES, "image/png") { }
            }
            io {
                assertThrows(PhotoFolderScopeError::class.java) {
                    NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, png.length(), GalleryMediaType.IMAGES, "image/jpeg") { }
                }
                assertThrows(PhotoFolderScopeError::class.java) {
                    NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, png.length() + 1, GalleryMediaType.IMAGES, "image/png") { }
                }
            }
        }
        val garbage = File(root, "claimed-photo.png").apply { writeText("not an image or video") }
        readOnly(garbage).use { descriptor ->
            io { assertThrows(PhotoFolderScopeError::class.java) {
                NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, garbage.length(), GalleryMediaType.IMAGES, "image/png") { }
            } }
        }
    }

    @Test fun nativeOwnerWithdrawalDuringMetadataInspectionCannotReturnAnObservation() = fixture<Unit> { root, io ->
        val file = File(root, "current.png"); val bitmap = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888)
        try { file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) } } finally { bitmap.recycle() }
        readOnly(file).use { descriptor ->
            io {
                var checks = 0
                assertThrows(PhotoFolderScopeError::class.java) {
                    NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, file.length(), GalleryMediaType.IMAGES, "image/png") {
                        if (++checks >= 2) DeviceFileControl.fail("explicit native owner withdrawal")
                    }
                }
                assertTrue(checks >= 2)
            }
        }
    }

    @Test fun videoNeedsNativeContainerMetadataAndActualVideoTrackNotOnlyAMimeClaim() = fixture<Unit> { root, io ->
        for (mode in listOf("valid", "absent", "audio_only", "wrong_mime", "dimensions", "too_many")) {
            val file = File(root, "metadata-$mode.mp4").apply { writeBytes(ByteArray(64) { 1 }) }
            readOnly(file).use { descriptor ->
                val source = DataSource.toDataSource(descriptor.fileDescriptor, 0, file.length())
                if (mode != "absent") {
                    ShadowMediaMetadataRetriever.addMetadata(source, MediaMetadataRetriever.METADATA_KEY_MIMETYPE, if (mode == "wrong_mime") "audio/mp4" else "video/mp4")
                    ShadowMediaMetadataRetriever.addMetadata(source, MediaMetadataRetriever.METADATA_KEY_HAS_VIDEO, "yes")
                    ShadowMediaMetadataRetriever.addMetadata(source, MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH, if (mode == "dimensions") "0" else "1920")
                    ShadowMediaMetadataRetriever.addMetadata(source, MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT, "1080")
                    ShadowMediaMetadataRetriever.addMetadata(source, MediaMetadataRetriever.METADATA_KEY_DURATION, "1000")
                    repeat(if (mode == "too_many") 17 else 1) {
                        val format = if (mode == "audio_only") MediaFormat.createAudioFormat("audio/aac", 48000, 2)
                            else MediaFormat.createVideoFormat("video/avc", 1920, 1080)
                        ShadowMediaExtractor.addTrack(source, format, byteArrayOf())
                    }
                }
                io {
                    if (mode == "valid") {
                        val result = NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, file.length(), GalleryMediaType.VIDEO, "video/mp4") { }
                        assertEquals(1920, result.width); assertEquals(1080, result.height); assertEquals(1000L, result.durationMs!!)
                        assertFalse(result.isSavedReceipt)
                    } else assertThrows(PhotoFolderScopeError::class.java) {
                        NativeIncomingMediaInspection.inspect(descriptor.fileDescriptor, file.length(), GalleryMediaType.VIDEO, "video/mp4") { }
                    }
                }
            }
        }
    }
}
