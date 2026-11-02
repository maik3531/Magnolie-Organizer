package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Looper
import androidx.activity.ComponentActivity
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class GalleryPhotoPermissionLauncherTest {
    private class Fixture(saved: Bundle? = null) : AutoCloseable {
        val activityController = Robolectric.buildActivity(ComponentActivity::class.java).create(saved)
        val activity = activityController.get()
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        var request: NativeGalleryRequest? = NativeGalleryRequest(receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
        val results = mutableListOf<Result<GalleryReadCoverage>>()
        val adapter = GalleryPhotoPermissionLauncher(activity, { request }) { results += it }
        private var destroyed = false
        init {
            Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).denyPermissions(
                Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            activityController.start().resume()
        }
        fun grant(vararg permissions: String) = Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).grantPermissions(*permissions)
        @Suppress("DEPRECATION")
        fun result(code: Int, permissions: Array<String>, flags: IntArray) {
            activity.onRequestPermissionsResult(code, permissions, flags)
            Shadows.shadowOf(Looper.getMainLooper()).idle()
        }
        fun destroy() { if (!destroyed) { destroyed = true; activityController.pause().stop().destroy() } }
        override fun close() { destroy() }
    }

    @Test fun actualAndroidxContractDoesNotPromptOnConstructionAndReadsRealFlagsNotResultBooleans() {
        Fixture().use { f ->
            val shadow = Shadows.shadowOf(f.activity)
            assertNull(shadow.lastRequestedPermission)
            f.adapter.request()
            val pending = shadow.lastRequestedPermission!!
            assertArrayEquals(arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED), pending.requestedPermissions)
            f.grant(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            f.result(pending.requestCode, pending.requestedPermissions, IntArray(2) { PackageManager.PERMISSION_GRANTED })
            assertEquals(GalleryReadCoverage.SELECTED_ONLY, f.results.single().getOrThrow())
            f.result(pending.requestCode, pending.requestedPermissions, IntArray(2) { PackageManager.PERMISSION_GRANTED })
            assertEquals(1, f.results.size)
        }
    }

    @Test fun genuineActivityPauseResumeRotatesProofsAndCannotLaunchFromBackground() {
        Fixture().use { f ->
            val before = f.adapter.access.accessEpoch()
            f.activityController.pause().stop()
            assertEquals("gallery_permission_foreground_required", assertThrows(PhotoFolderScopeError::class.java) { f.adapter.request() }.code)
            assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
            f.activityController.restart().start().resume()
            assertNotEquals(before, f.adapter.access.accessEpoch())
            f.adapter.request()
            assertNotNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
        }
    }

    @Test fun actualSystemResultCannotMoveToAChangedSourceOwnerOrEnableAnythingImplicitly() {
        Fixture().use { f ->
            f.adapter.request()
            val pending = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            f.request = NativeGalleryRequest(f.receiver.copy(owner = Any()), "b".repeat(64), setOf(GallerySourceKind.CAMERA))
            f.grant(Manifest.permission.READ_MEDIA_IMAGES)
            f.result(pending.requestCode, pending.requestedPermissions, IntArray(2) { PackageManager.PERMISSION_GRANTED })
            val failure = f.results.single().exceptionOrNull()
            assertTrue(failure is PhotoFolderScopeError)
            assertEquals("gallery_permission_source_changed", (failure as PhotoFolderScopeError).code)
            assertEquals(GalleryReadCoverage.FULL_IMAGES, AndroidGalleryReadPermissions.observe(f.activity))
        }
    }

    @Test fun recreatedActivityDoesNotReconstructAnOldNativePermissionTicketFromSavedRegistryState() {
        val state = Bundle()
        val old = Fixture()
        val epoch = old.adapter.access.accessEpoch()
        old.adapter.request()
        val pending = Shadows.shadowOf(old.activity).lastRequestedPermission!!
        old.activityController.saveInstanceState(state)
        old.destroy()
        assertThrows(PhotoFolderScopeError::class.java) { old.adapter.access.accessEpoch() }
        Fixture(state).use { fresh ->
            assertNotEquals(epoch, fresh.adapter.access.accessEpoch())
            fresh.grant(Manifest.permission.READ_MEDIA_IMAGES)
            fresh.result(pending.requestCode, pending.requestedPermissions, IntArray(2) { PackageManager.PERMISSION_GRANTED })
            assertTrue(fresh.results.isEmpty()); assertTrue(old.results.isEmpty())
            assertNull(Shadows.shadowOf(fresh.activity).lastRequestedPermission)
        }
    }

    @Test fun closingTheNativeOwnerCancelsItsPendingResultAndRejectsFurtherRequests() {
        Fixture().use { f ->
            f.adapter.request()
            val pending = Shadows.shadowOf(f.activity).lastRequestedPermission!!
            f.adapter.close(); f.adapter.close()
            f.result(pending.requestCode, pending.requestedPermissions, IntArray(2) { PackageManager.PERMISSION_GRANTED })
            assertTrue(f.results.isEmpty())
            assertEquals("gallery_access_controller_closed", assertThrows(PhotoFolderScopeError::class.java) { f.adapter.request() }.code)
        }
    }
}
