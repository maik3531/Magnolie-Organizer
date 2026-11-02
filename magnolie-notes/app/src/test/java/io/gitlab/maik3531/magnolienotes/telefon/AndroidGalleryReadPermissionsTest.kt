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

/** Existing cached SDK35 runtime; synthetic permission grants, not physical consent. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class AndroidGalleryReadPermissionsTest {
    @Test fun actualModernPermissionFlagsDistinguishFullSelectedOnlyAndNoImageVisibility() {
        val context = RuntimeEnvironment.getApplication()
        val shadow = Shadows.shadowOf(context as Application)
        shadow.denyPermissions(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
        assertEquals(GalleryReadCoverage.NONE, AndroidGalleryReadPermissions.observe(context))
        shadow.grantPermissions(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
        assertEquals(GalleryReadCoverage.SELECTED_ONLY, AndroidGalleryReadPermissions.observe(context))
        shadow.grantPermissions(Manifest.permission.READ_MEDIA_IMAGES)
        assertEquals(GalleryReadCoverage.FULL_IMAGES, AndroidGalleryReadPermissions.observe(context))
        shadow.denyPermissions(Manifest.permission.READ_MEDIA_IMAGES)
        assertEquals(GalleryReadCoverage.SELECTED_ONLY, AndroidGalleryReadPermissions.observe(context))
        shadow.denyPermissions(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
        assertEquals(GalleryReadCoverage.NONE, AndroidGalleryReadPermissions.observe(context))
    }

    @Test fun legacyStoragePermissionDoesNotPretendToGrantModernPhotoAccessOrActivateDiscovery() {
        val context = RuntimeEnvironment.getApplication()
        val shadow = Shadows.shadowOf(context as Application)
        shadow.denyPermissions(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
        shadow.grantPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
        assertEquals(GalleryReadCoverage.NONE, AndroidGalleryReadPermissions.observe(context))
        shadow.grantPermissions(Manifest.permission.READ_MEDIA_IMAGES)
        val catalog = AndroidGalleryAlbumDiscovery(context, { null }) { throw AssertionError("Disabled source inspected photo access") }.discover()
        assertTrue(catalog.albums.isEmpty()); assertNull(catalog.policyEpoch); assertFalse(catalog.provesFileDeletion)
    }
}
