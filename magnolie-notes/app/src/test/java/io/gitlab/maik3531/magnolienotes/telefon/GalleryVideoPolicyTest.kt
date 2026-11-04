package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.File
import java.io.IOException
import java.nio.file.Files
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = Application::class)
class GalleryVideoPolicyTest {
    private fun assertSamePhotoActivation(before: NativeGalleryRequest, after: NativeGalleryRequest?) {
        assertNotNull(after); assertSame(before.receiver, after!!.receiver)
        assertEquals(before.policyEpoch, after.policyEpoch); assertEquals(before.kinds, after.kinds)
        assertEquals(GalleryMediaType.IMAGES, after.mediaType)
    }
    private class Fixture : AutoCloseable {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "gallery-video-policy330-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val owner = Any()
        var receiver: NativePhotoReceiver? = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), owner, "f".repeat(64),
            true, true, true, true, true, true, 1, "1".repeat(64))
        var configurer: NativeGalleryConfigurer? = NativeGalleryConfigurer("receiver_fixture_01", "e".repeat(64), owner,
            "f".repeat(64), true, true, true, true, "1".repeat(64))
        val peer = NativeFileControlPeer("receiver_fixture_01", "e".repeat(64), Any(), true, true, true, true, true, "1".repeat(64))
        var boundary: (String) -> Unit = {}
        val index = PhotoSourceJobIndex(root, protection) { boundary(it) }
        val controller = GalleryPhotoPolicyController.forAuthenticatedConfigurer(index, { receiver }, { configurer })
        val grants = NativeGalleryFileGrantPolicy({ peer }, { index.galleryPolicy() }, { true })
        fun enablePhotos() = controller.configure(index.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA))
        override fun close() { index.close(); root.deleteRecursively() }
    }

    @Test fun explicitVideoPolicyRetainsPhotoGrantAndCannotTurnPhotoOsPermissionIntoVideoRead() {
        Fixture().use { f ->
            val photos = f.enablePhotos(); val photoRequest = f.controller.currentRequest()!!; val grant = f.grants.current()!!.grants
            assertNull(photos.policy!!.videos); assertNull(f.controller.currentRequest(GalleryMediaType.VIDEO))
            val saved = f.controller.configureVideos(photos, true)
            assertEquals(JsonPrimitive(4), saved.policy!!.wire()["format"])
            assertEquals(saved.policy!!.wire(), GalleryPhotoPolicy.parse(saved.policy!!.wire()).wire())
            assertSamePhotoActivation(photoRequest, f.controller.currentRequest()); assertEquals(grant, f.grants.current()!!.grants)
            val video = f.controller.currentRequest(GalleryMediaType.VIDEO)!!
            assertEquals(GalleryMediaType.VIDEO, video.mediaType)
            assertNotEquals(photoRequest.policyEpoch, video.policyEpoch)
            val app = RuntimeEnvironment.getApplication()
            Shadows.shadowOf(app).grantPermissions(Manifest.permission.READ_MEDIA_IMAGES)
            Shadows.shadowOf(app).denyPermissions(Manifest.permission.READ_MEDIA_VIDEO, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            assertEquals(GalleryReadCoverage.FULL_IMAGES, AndroidGalleryReadPermissions.observe(app))
            assertEquals(GalleryReadCoverage.NONE, AndroidGalleryReadPermissions.observe(app, GalleryMediaType.VIDEO))
            val catalog = AndroidGalleryAlbumDiscovery(app, { f.controller.currentRequest(GalleryMediaType.VIDEO) },
                mediaType = GalleryMediaType.VIDEO).discover()
            assertEquals(GalleryReadCoverage.NONE, catalog.coverage); assertTrue(catalog.albums.isEmpty())
            assertTrue(f.index.jobs().isEmpty())
        }
    }

    @Test fun liveVideoCapabilityWithdrawalVetoesReadWithoutChangingPhotoGrantOrSavedPolicy() {
        Fixture().use { f ->
            var available = false
            val controller = GalleryPhotoPolicyController.forAuthenticatedConfigurer(f.index, { f.receiver }, { f.configurer }, { available })
            val photos = f.enablePhotos(); val grant = f.grants.current()!!.grants
            val photo = controller.currentRequest()!!
            assertEquals("gallery_video_handlers_unavailable", assertThrows(PhotoFolderScopeError::class.java) {
                controller.configureVideos(photos, true)
            }.code)
            assertEquals(photos, f.index.galleryPolicy())
            available = true
            val enabled = controller.configureVideos(photos, true)
            assertNotNull(controller.currentRequest(GalleryMediaType.VIDEO))
            available = false
            assertNull(controller.currentRequest(GalleryMediaType.VIDEO))
            assertSamePhotoActivation(photo, controller.currentRequest())
            assertEquals(grant, f.grants.current()!!.grants); assertEquals(enabled, f.index.galleryPolicy())
            // A local decrease remains permitted even after feature withdrawal.
            assertFalse(controller.configureVideos(enabled, false).policy!!.videos!!.enabled)
            assertEquals(grant, f.grants.current()!!.grants)
        }
    }

    @Test fun capabilityWithdrawalDuringVideoCasCannotPublishPositiveReadOrRotatePhotoGrant() {
        for (point in listOf("gallery-policy-fenced", "gallery-policy-published")) Fixture().use { f ->
            var available = true
            val controller = GalleryPhotoPolicyController.forAuthenticatedConfigurer(f.index, { f.receiver }, { f.configurer }, { available })
            val photos = f.enablePhotos(); val grant = f.grants.current()!!.grants
            f.boundary = { if (it == point) available = false }
            assertThrows(PhotoFolderScopeError::class.java) { controller.configureVideos(photos, true) }
            val held = f.index.galleryPolicy(); assertTrue(held.repairPending)
            assertEquals(photos.policy!!.epoch, held.policy!!.epoch)
            assertEquals(photos.policy!!.fileGrantRevision, held.policy!!.fileGrantRevision)
            assertNull(controller.currentRequest(GalleryMediaType.VIDEO)); assertNull(controller.currentRequest())
            assertEquals(grant, f.grants.current()!!.grants); assertFalse(f.grants.current()!!.policyReady)
            available = true
            assertNull(controller.currentRequest(GalleryMediaType.VIDEO)) // An uncertain controller cannot be resurrected by a marker.
            assertTrue(f.index.jobs().isEmpty())
        }
    }

    @Test fun videoDisableAndRenewalUseIndependentEpochWithoutPhotoConsentOrGrantChurn() {
        Fixture().use { f ->
            val photos = f.enablePhotos(); val grant = f.grants.current()!!.grants; val request = f.controller.currentRequest()!!
            val enabled = f.controller.configureVideos(photos, true)
            val old = f.controller.currentRequest(GalleryMediaType.VIDEO)!!
            val disabled = f.controller.configureVideos(enabled, false)
            assertNull(f.controller.currentRequest(GalleryMediaType.VIDEO))
            assertSamePhotoActivation(request, f.controller.currentRequest()); assertEquals(grant, f.grants.current()!!.grants)
            assertFalse(disabled.policy!!.videos!!.enabled)
            val renewed = f.controller.configureVideos(disabled, true)
            assertEquals(3L, renewed.policy!!.videos!!.revision)
            assertNotEquals(old.policyEpoch, f.controller.currentRequest(GalleryMediaType.VIDEO)!!.policyEpoch)
            assertSamePhotoActivation(request, f.controller.currentRequest()); assertEquals(grant, f.grants.current()!!.grants)
            assertEquals(renewed, f.controller.configureVideos(renewed, true))
            assertEquals(renewed, f.index.galleryPolicy())
        }
    }

    @Test fun metadataConfigurerWithoutAcknowledgedDataReceiverCannotActivateVideoRead() {
        Fixture().use { f ->
            val empty = f.index.galleryPolicy()
            assertThrows(PhotoFolderScopeError::class.java) { f.controller.configureVideos(empty, true) }
            assertEquals(empty, f.index.galleryPolicy())
            val photos = f.enablePhotos(); f.receiver = null
            val video = f.controller.configureVideos(photos, true)
            assertTrue(video.policy!!.videos!!.enabled)
            assertNull(f.controller.currentRequest()); assertNull(f.controller.currentRequest(GalleryMediaType.VIDEO))
            f.configurer = null
            assertThrows(PhotoFolderScopeError::class.java) { f.controller.configureVideos(video, false) }
            assertEquals(video, f.index.galleryPolicy())
        }
    }

    @Test fun strictVideoRecordRejectsAliasesMissingFieldsAndCounterConfusion() {
        Fixture().use { f ->
            val saved = f.controller.configureVideos(f.enablePhotos(), true); val valid = saved.policy!!.wire()
            val video = valid["videos"] as JsonObject
            fun badVideo(field: String, value: JsonPrimitive) = JsonObject(valid + ("videos" to JsonObject(video + (field to value))))
            val invalid = listOf(JsonObject(valid - "videos"), JsonObject(valid - "permission_revision"),
                JsonObject(valid + ("permission_revision" to JsonPrimitive(true))),
                JsonObject(valid + ("permission_revision" to JsonPrimitive("2"))),
                JsonObject(valid + ("permission_revision" to JsonPrimitive(0))),
                JsonObject(valid + ("permission_revision" to JsonPrimitive(saved.policy!!.revision + 1))),
                badVideo("enabled", JsonPrimitive("true")), badVideo("revision", JsonPrimitive(-1)),
                badVideo("epoch", JsonPrimitive("not-an-epoch")), badVideo("read_granted", JsonPrimitive(true)),
                JsonObject(valid + ("format" to JsonPrimitive(3))))
            for (value in invalid) assertThrows(PhotoFolderScopeError::class.java) { GalleryPhotoPolicy.parse(value) }
            assertEquals(saved, f.index.galleryPolicy())
        }
    }

    @Test fun nativeIndexRejectsPhotoPermissionRollbackAndVideoPolicyErasureBeforeAnyMutation() {
        Fixture().use { f ->
            val saved = f.controller.configureVideos(f.enablePhotos(), true); val old = saved.policy!!
            val rollback = GalleryPhotoPolicy(old.receiverId, old.receiverIdentitySha256, old.epoch, old.enabled, old.kinds,
                old.revision + 1, 4, old.pairingEpoch, old.videos, old.fileGrantRevision - 1)
            val erased = GalleryPhotoPolicy(old.receiverId, old.receiverIdentitySha256, old.epoch, old.enabled, old.kinds,
                old.revision + 1, 3, old.pairingEpoch)
            val changedPhoto = GalleryPhotoPolicy(old.receiverId, old.receiverIdentitySha256, "b".repeat(64), old.enabled, old.kinds,
                old.revision + 1, 4, old.pairingEpoch, old.videos, old.fileGrantRevision)
            for (next in listOf(rollback, erased, changedPhoto)) {
                assertThrows(PhotoFolderScopeError::class.java) { f.index.compareAndSetGalleryPolicy(saved, next) { true } }
                assertEquals(saved, f.index.galleryPolicy())
            }
        }
    }

    @Test fun uncertainVideoCasKeepsOriginalPhotoGrantBytesAndHoldsBothReadActivations() {
        for (point in listOf("gallery-policy-fenced", "gallery-policy-published")) Fixture().use { f ->
            val photos = f.enablePhotos(); val grant = f.grants.current()!!.grants
            f.boundary = { if (it == point) throw IOException("fixture video policy publication uncertain") }
            assertThrows(IOException::class.java) { f.controller.configureVideos(photos, true) }
            val held = f.index.galleryPolicy(); assertTrue(held.repairPending)
            assertEquals(photos.policy!!.epoch, held.policy!!.epoch)
            assertEquals(photos.policy!!.fileGrantRevision, held.policy!!.fileGrantRevision)
            val projected = f.grants.current()!!; assertEquals(grant, projected.grants); assertFalse(projected.policyReady)
            assertNull(f.controller.currentRequest()); assertNull(f.controller.currentRequest(GalleryMediaType.VIDEO))
            assertTrue(f.index.jobs().isEmpty())
        }
    }

    @Test fun basePhotoRevocationStillStopsBothMediaDomainsWithoutDroppingVideoPreference() {
        Fixture().use { f ->
            val enabled = f.controller.configureVideos(f.enablePhotos(), true)
            assertNotNull(f.controller.currentRequest(GalleryMediaType.VIDEO))
            val grant = f.grants.current()!!.grants
            f.receiver = null; f.configurer = null
            val disabled = f.controller.disableLocally(enabled)
            assertFalse(disabled.policy!!.enabled); assertEquals(enabled.policy!!.videos, disabled.policy!!.videos)
            assertNull(f.controller.currentRequest()); assertNull(f.controller.currentRequest(GalleryMediaType.VIDEO))
            assertFalse(f.grants.current()!!.grants.sendFiles)
            assertTrue(f.grants.current()!!.grants.revision > grant.revision)
        }
    }
}
