package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.pm.PackageManager
import android.os.Looper
import android.widget.EditText
import androidx.activity.ComponentActivity
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.File
import java.nio.file.Files
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class GalleryPhotoPermissionHostTest {
    private class Fixture(video: Boolean = false) : AutoCloseable {
        val activityController = Robolectric.buildActivity(ComponentActivity::class.java).create()
        val activity = activityController.get()
        val host = GalleryPhotoPermissionHost(activity) // Genuine early registration.
        val videoHost = if (video) GalleryPhotoPermissionHost(activity, GalleryMediaType.VIDEO) else null
        val roots = mutableListOf<File>()
        val workflows = mutableListOf<NativeGalleryPhotoWorkflow>()
        init {
            Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).denyPermissions(
                Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            if (video) Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).denyPermissions(Manifest.permission.READ_MEDIA_VIDEO)
            activityController.start().resume()
        }
        fun workflow(): NativeGalleryPhotoWorkflow {
            val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "gallery-host330-").toFile().also { roots += it }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64),
                true, true, true, true, true, true, 1, "1".repeat(64))
            return NativeGalleryPhotoWorkflow(activity, root, "sender_fixture_01", protection) { receiver }.also { workflows += it }
        }
        fun activate(workflow: NativeGalleryPhotoWorkflow) {
            workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
        }
        fun epoch(): String {
            val launcher = GalleryPhotoPermissionHost::class.java.getDeclaredField("launcher").also { it.isAccessible = true }.get(host) as GalleryPhotoPermissionLauncher
            return launcher.access.accessEpoch()
        }
        @Suppress("DEPRECATION") fun result(code: Int, permissions: Array<String>) {
            activity.onRequestPermissionsResult(code, permissions, IntArray(permissions.size) { PackageManager.PERMISSION_GRANTED })
            Shadows.shadowOf(Looper.getMainLooper()).idle()
        }
        override fun close() {
            workflows.forEach { it.close() }
            activityController.pause().stop().destroy()
            roots.forEach { it.deleteRecursively() }
        }
    }

    @Test fun lateSourceAttachmentUsesEarlyLauncherWithoutPromptRecreationOrDraftChanges() {
        Fixture().use { f ->
            val draft = EditText(f.activity).also { it.setText("Unsaved fixture draft") }
            f.activity.setContentView(draft)
            val workflow = f.workflow(); val results = mutableListOf<Result<GalleryReadCoverage>>()
            workflow.attachPermissionHost(f.host) { results += it }
            assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
            assertThrows(PhotoFolderScopeError::class.java) { workflow.requestReadPermission() }
            assertFalse(f.host.requestPending)
            f.activate(workflow)
            assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
            workflow.requestReadPermission()
            val pending = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            assertTrue(f.host.requestPending)
            Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).grantPermissions(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            f.result(pending.requestCode, pending.requestedPermissions)
            assertEquals(GalleryReadCoverage.SELECTED_ONLY, results.single().getOrThrow())
            assertFalse(f.host.requestPending)
            assertEquals("Unsaved fixture draft", draft.text.toString())
            assertSame(f.activity, draft.context)
        }
    }

    @Test fun pendingOsCallbackCannotBeReassignedToAReplacementWorkflow() {
        Fixture().use { f ->
            val first = f.workflow(); val second = f.workflow()
            f.activate(first); f.activate(second)
            val oldResults = mutableListOf<Result<GalleryReadCoverage>>()
            val newResults = mutableListOf<Result<GalleryReadCoverage>>()
            first.attachPermissionHost(f.host) { oldResults += it }
            first.requestReadPermission()
            val old = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            assertThrows(PhotoFolderScopeError::class.java) { second.attachPermissionHost(f.host) { newResults += it } }
            first.close()
            assertTrue(f.host.requestPending)
            assertThrows(PhotoFolderScopeError::class.java) { second.attachPermissionHost(f.host) { newResults += it } }
            f.result(old.requestCode, old.requestedPermissions)
            assertTrue(oldResults.isEmpty()); assertTrue(newResults.isEmpty()); assertFalse(f.host.requestPending)
            second.attachPermissionHost(f.host) { newResults += it }
            second.requestReadPermission()
            val fresh = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            f.result(fresh.requestCode, fresh.requestedPermissions)
            assertEquals(GalleryReadCoverage.NONE, newResults.single().getOrThrow()) // Map is not OS authority.
            assertTrue(oldResults.isEmpty())
        }
    }

    @Test fun replacingNativeOwnerRotatesAccessProofAndOldCloseCannotDetachNewOwner() {
        Fixture().use { f ->
            val first = f.workflow(); val second = f.workflow()
            f.activate(first); f.activate(second)
            first.attachPermissionHost(f.host) { }
            val original = f.epoch()
            second.attachPermissionHost(f.host) { }
            assertNotEquals(original, f.epoch())
            assertThrows(PhotoFolderScopeError::class.java) { first.requestReadPermission() }
            val current = f.epoch()
            first.close()
            assertEquals(current, f.epoch())
            val results = mutableListOf<Result<GalleryReadCoverage>>()
            // Same owner attachment is idempotent, even while a request exists.
            second.attachPermissionHost(f.host) { results += it }
            second.requestReadPermission()
            second.attachPermissionHost(f.host) { results += it }
            assertTrue(f.host.requestPending)
        }
    }

    @Test fun independentEarlyVideoHostRequestsOnlyVideoPermissionAndNeverConsumesImageCallback() {
        Fixture(video = true).use { f ->
            val workflow = f.workflow(); val photos = mutableListOf<Result<GalleryReadCoverage>>()
            val videos = mutableListOf<Result<GalleryReadCoverage>>()
            workflow.attachPermissionHost(f.host) { photos += it }
            workflow.attachPermissionHost(f.videoHost!!) { videos += it }
            f.activate(workflow)
            assertThrows(PhotoFolderScopeError::class.java) { workflow.requestReadPermission(GalleryMediaType.VIDEO) }
            assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
            workflow.configureVideos(workflow.savedPolicy(), true)
            assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
            val photoAccess = f.epoch()
            workflow.requestReadPermission(GalleryMediaType.VIDEO)
            val video = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            assertTrue(Manifest.permission.READ_MEDIA_VIDEO in video.requestedPermissions)
            assertFalse(Manifest.permission.READ_MEDIA_IMAGES in video.requestedPermissions)
            assertTrue(f.videoHost.requestPending); assertFalse(f.host.requestPending)
            assertEquals("gallery_permission_request_pending", assertThrows(PhotoFolderScopeError::class.java) { workflow.requestReadPermission() }.code)
            assertEquals(video.requestCode, Shadows.shadowOf(f.activity).lastRequestedPermission!!.requestCode)
            assertEquals(photoAccess, f.epoch())
            f.result(video.requestCode, video.requestedPermissions)
            assertNotEquals(photoAccess, f.epoch()) // Native OS selection changes invalidate both media READ proofs.
            assertEquals(GalleryReadCoverage.NONE, videos.single().getOrThrow()) // Boolean callback is not OS READ.
            assertTrue(photos.isEmpty())
            Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).denyPermissions(
                Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            workflow.requestReadPermission()
            val photo = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            assertTrue(Manifest.permission.READ_MEDIA_IMAGES in photo.requestedPermissions)
            assertFalse(Manifest.permission.READ_MEDIA_VIDEO in photo.requestedPermissions)
            // A second OS request can already have returned a denied result.
            // Replaying its callback must still not consume another media owner.
            f.result(photo.requestCode, photo.requestedPermissions)
            assertEquals(GalleryReadCoverage.NONE, photos.single().getOrThrow()); assertEquals(1, videos.size)
        }
    }

    @Test fun firstPendingImageDialogAlsoExcludesVideoPermissionLaunch() {
        Fixture(video = true).use { f ->
            val workflow = f.workflow(); f.activate(workflow)
            workflow.configureVideos(workflow.savedPolicy(), true)
            val photos = mutableListOf<Result<GalleryReadCoverage>>()
            workflow.attachPermissionHost(f.host) { photos += it }
            workflow.attachPermissionHost(f.videoHost!!) { throw AssertionError("Overlapping video permission launched") }
            workflow.requestReadPermission()
            val image = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            assertTrue(f.host.requestPending); assertFalse(f.videoHost.requestPending)
            assertEquals("gallery_permission_request_pending", assertThrows(PhotoFolderScopeError::class.java) {
                workflow.requestReadPermission(GalleryMediaType.VIDEO)
            }.code)
            assertEquals(image.requestCode, Shadows.shadowOf(f.activity).lastRequestedPermission!!.requestCode)
            assertFalse(f.videoHost.requestPending)
            f.result(image.requestCode, image.requestedPermissions)
            assertEquals(GalleryReadCoverage.NONE, photos.single().getOrThrow())
        }
    }

    @Test fun pendingVideoCallbackCannotRestoreRevokedVideoPolicyOrAffectPhotoOwner() {
        Fixture(video = true).use { f ->
            val workflow = f.workflow(); f.activate(workflow)
            val photoEpoch = workflow.currentRequest()!!.policyEpoch
            workflow.configureVideos(workflow.savedPolicy(), true)
            val videos = mutableListOf<Result<GalleryReadCoverage>>()
            workflow.attachPermissionHost(f.host) { throw AssertionError("Video callback reached photo host") }
            workflow.attachPermissionHost(f.videoHost!!) { videos += it }
            workflow.requestReadPermission(GalleryMediaType.VIDEO)
            val video = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            workflow.configureVideos(workflow.savedPolicy(), false)
            Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).grantPermissions(Manifest.permission.READ_MEDIA_VIDEO)
            f.result(video.requestCode, video.requestedPermissions)
            assertTrue(videos.single().isFailure); assertFalse(f.videoHost.requestPending)
            assertNull(workflow.currentRequest(GalleryMediaType.VIDEO))
            assertEquals(photoEpoch, workflow.currentRequest()!!.policyEpoch); assertFalse(f.host.requestPending)
        }
    }
}
