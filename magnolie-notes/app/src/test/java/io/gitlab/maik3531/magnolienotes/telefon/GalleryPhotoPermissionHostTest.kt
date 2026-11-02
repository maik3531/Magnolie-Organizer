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
    private class Fixture : AutoCloseable {
        val activityController = Robolectric.buildActivity(ComponentActivity::class.java).create()
        val activity = activityController.get()
        val host = GalleryPhotoPermissionHost(activity) // Genuine early registration.
        val roots = mutableListOf<File>()
        val workflows = mutableListOf<NativeGalleryPhotoWorkflow>()
        init {
            Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).denyPermissions(
                Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
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
}
