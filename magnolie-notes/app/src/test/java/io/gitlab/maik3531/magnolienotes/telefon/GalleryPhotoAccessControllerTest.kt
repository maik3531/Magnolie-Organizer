package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [AndroidGalleryVolumeAccessTest.MountedVolumes::class])
class GalleryPhotoAccessControllerTest {
    private class Fixture {
        val context = RuntimeEnvironment.getApplication()
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        var request: NativeGalleryRequest? = NativeGalleryRequest(receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
        var clock = 100L
        val controller = GalleryPhotoAccessController(context, { request }) { clock }
        fun permission() = Shadows.shadowOf(context as Application)
    }

    @Test fun nothingLaunchesUntilAnActivatedNativeForegroundRequestAndOnlyReadPermissionsAreRequested() {
        val f = Fixture()
        assertEquals("gallery_permission_foreground_required", assertThrows(PhotoFolderScopeError::class.java) { f.controller.preparePermissionRequest() }.code)
        f.controller.onResume(); f.request = null
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.preparePermissionRequest() }
        f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
        val before = f.controller.accessEpoch(); val ticket = f.controller.preparePermissionRequest()
        assertNotEquals(before, f.controller.accessEpoch())
        assertEquals(listOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED), ticket.permissions)
        assertThrows(UnsupportedOperationException::class.java) { (ticket.permissions as MutableList<String>).clear() }
        var launches = 0
        f.controller.launch(ticket) { assertEquals(ticket.permissions, it.toList()); launches++ }
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.launch(ticket) { launches++ } }
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.preparePermissionRequest() }
        assertEquals(1, launches)
        assertEquals(GalleryReadCoverage.NONE, f.controller.complete(ticket))
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.complete(ticket) }
    }

    @Test fun permissionResultUsesActualOsReadbackAndDistinguishesSelectedFromFull() {
        val f = Fixture(); f.controller.onResume()
        for (coverage in listOf(GalleryReadCoverage.NONE, GalleryReadCoverage.SELECTED_ONLY, GalleryReadCoverage.FULL_IMAGES)) {
            f.permission().denyPermissions(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            val ticket = f.controller.preparePermissionRequest()
            f.controller.launch(ticket) { }
            when (coverage) {
                GalleryReadCoverage.FULL_IMAGES -> f.permission().grantPermissions(Manifest.permission.READ_MEDIA_IMAGES)
                GalleryReadCoverage.SELECTED_ONLY -> f.permission().grantPermissions(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
                else -> Unit
            }
            val before = f.controller.accessEpoch()
            assertEquals(coverage, f.controller.complete(ticket))
            assertNotEquals(before, f.controller.accessEpoch())
        }
    }

    @Test fun ownerPolicyIdentityGrantOrDeadlineChangesCannotApplyAStaleSystemDialogResult() {
        for (change in listOf("owner", "policy", "identity", "pairing", "grant", "kinds", "timeout", "clock")) {
            val f = Fixture(); f.controller.onResume()
            val ticket = f.controller.preparePermissionRequest(); f.controller.launch(ticket) { }
            when (change) {
                "owner" -> f.request = NativeGalleryRequest(f.receiver.copy(owner = Any()), "b".repeat(64), f.request!!.kinds)
                "policy" -> f.request = NativeGalleryRequest(f.receiver, "c".repeat(64), f.request!!.kinds)
                "identity" -> f.request = NativeGalleryRequest(f.receiver.copy(identitySha256 = "c".repeat(64)), "b".repeat(64), f.request!!.kinds)
                "pairing" -> f.request = NativeGalleryRequest(f.receiver.copy(pairingEpoch = "c".repeat(64)), "b".repeat(64), f.request!!.kinds)
                "grant" -> f.request = NativeGalleryRequest(f.receiver.copy(receiveGranted = false), "b".repeat(64), f.request!!.kinds)
                "kinds" -> f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.SCREENSHOTS))
                "timeout" -> f.clock += GalleryPhotoAccessController.MAX_PROMPT_MS + 1
                else -> f.clock = 0
            }
            f.permission().grantPermissions(Manifest.permission.READ_MEDIA_IMAGES)
            assertEquals("gallery_permission_source_changed", assertThrows(PhotoFolderScopeError::class.java) { f.controller.complete(ticket) }.code)
            // Permissions are app-wide: stale source consent must not revoke
            // OS rights possibly used by backup/import or another feature.
            assertEquals(GalleryReadCoverage.FULL_IMAGES, AndroidGalleryReadPermissions.observe(f.context))
        }
    }

    @Test fun pauseBlocksLaunchingAndResumeOrAccessChangesRotateNativeProofsWithoutChangingOsRights() {
        val f = Fixture(); f.controller.onResume()
        f.permission().grantPermissions(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
        val ticket = f.controller.preparePermissionRequest()
        val before = f.controller.accessEpoch()
        f.controller.onPause()
        assertEquals("gallery_permission_foreground_required", assertThrows(PhotoFolderScopeError::class.java) { f.controller.launch(ticket) { fail("background prompt") } }.code)
        f.controller.onResume(); assertNotEquals(before, f.controller.accessEpoch())
        val resumed = f.controller.accessEpoch()
        f.controller.onAccessChanged(); assertNotEquals(resumed, f.controller.accessEpoch())
        assertEquals(GalleryReadCoverage.SELECTED_ONLY, AndroidGalleryReadPermissions.observe(f.context))
        f.controller.cancel()
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.launch(ticket) { fail("cancelled prompt") } }
    }

    @Test fun foreignTicketsLaunchFailuresAndClosedNativeOwnersCannotAuthorizeRequests() {
        val f = Fixture(); f.controller.onResume()
        val ticket = f.controller.preparePermissionRequest()
        val foreign = GalleryPhotoPermissionTicket(ticket.activation, ticket.startedMs, ticket.permissions)
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.launch(foreign) { fail("foreign prompt") } }
        assertThrows(IllegalStateException::class.java) { f.controller.launch(ticket) { throw IllegalStateException("native launcher unavailable") } }
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.complete(ticket) }
        f.controller.close()
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.accessEpoch() }
        assertThrows(PhotoFolderScopeError::class.java) { f.controller.preparePermissionRequest() }
    }

    @Test @Config(sdk = [28]) fun legacyControllerRequestsOnlyActualReadStoragePermission() {
        val f = Fixture(); f.controller.onResume()
        val ticket = f.controller.preparePermissionRequest()
        assertEquals(listOf(Manifest.permission.READ_EXTERNAL_STORAGE), ticket.permissions)
        f.controller.launch(ticket) { }
        f.permission().grantPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
        assertEquals(GalleryReadCoverage.FULL_IMAGES, f.controller.complete(ticket))
    }

    @Test fun typedVideoControllerRejectsImageActivationAndCrossMediaResultEvenWithSameOwnerAndEpoch() {
        val f = Fixture()
        GalleryPhotoAccessController(f.context, { f.request }, GalleryMediaType.VIDEO) { f.clock }.let { video ->
            video.onResume()
            val before = video.accessEpoch()
            assertEquals("gallery_media_scope_changed", assertThrows(PhotoFolderScopeError::class.java) { video.preparePermissionRequest() }.code)
            assertEquals(before, video.accessEpoch())
            f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA), GalleryMediaType.VIDEO)
            val ticket = video.preparePermissionRequest()
            assertEquals(listOf(Manifest.permission.READ_MEDIA_VIDEO, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED), ticket.permissions)
            video.launch(ticket) { }
            f.permission().grantPermissions(Manifest.permission.READ_MEDIA_VIDEO)
            f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA), GalleryMediaType.IMAGES)
            assertEquals("gallery_permission_source_changed", assertThrows(PhotoFolderScopeError::class.java) { video.complete(ticket) }.code)
            assertEquals(GalleryReadCoverage.FULL_VIDEOS, AndroidGalleryReadPermissions.observe(f.context, GalleryMediaType.VIDEO))
            video.close()
        }
    }
}
