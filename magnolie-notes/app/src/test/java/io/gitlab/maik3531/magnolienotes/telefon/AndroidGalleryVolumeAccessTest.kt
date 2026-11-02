package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.shadows.ShadowContentResolver
import org.robolectric.shadows.ShadowMediaStore

/** API29 runtime is already in the existing offline Robolectric cache. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29], application = Application::class, shadows = [AndroidGalleryVolumeAccessTest.MountedVolumes::class])
class AndroidGalleryVolumeAccessTest {
    // Robolectric 4.14 shadows StorageVolume listings, not API29's hidden
    // StorageManager.getVolumes() binder. Inject only the mount-name boundary;
    // the real framework getVersion(context, volume) and provider call run below.
    @Implements(MediaStore::class)
    class MountedVolumes : ShadowMediaStore() {
        companion object {
            @JvmStatic @Implementation(minSdk = 29)
            fun getExternalVolumeNames(context: Context): Set<String> = setOf("external_primary", "1234-5678")
        }
    }
    private class Provider : ContentProvider() {
        val versions = mutableMapOf("external_primary" to "primary-namespace", "1234-5678" to "card-namespace")
        val calls = mutableListOf<String>()
        override fun onCreate() = true
        override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
            check(method == "get_version")
            val volume = requireNotNull(extras?.getString(Intent.EXTRA_TEXT))
            calls += volume
            return Bundle().apply { putString(Intent.EXTRA_TEXT, versions.getValue(volume)) }
        }
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, sort: String?): Cursor =
            throw AssertionError("Version observation must not enumerate image contents")
        override fun getType(uri: Uri): String = throw AssertionError("Unexpected image metadata request")
        override fun insert(uri: Uri, values: ContentValues?): Uri = throw AssertionError("Read-only access wrote metadata")
        override fun update(uri: Uri, values: ContentValues?, where: String?, args: Array<out String>?): Int = throw AssertionError("Read-only access wrote metadata")
        override fun delete(uri: Uri, where: String?, args: Array<out String>?): Int = throw AssertionError("Read-only access deleted metadata")
    }
    private fun setup(): Pair<Context, Provider> {
        val context = RuntimeEnvironment.getApplication()
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
        val provider = Provider()
        provider.attachInfo(context, ProviderInfo().apply { authority = "media"; exported = true })
        ShadowContentResolver.registerProviderInternal("media", provider)
        return context to provider
    }

    @Test fun actualApi29ObservesEachMountedVolumeNamespaceInsteadOfReusingThePrimaryVersion() {
        val (context, provider) = setup()
        val environment = AndroidGalleryAccessEnvironment(context) { "a".repeat(64) }
        assertEquals("primary-namespace", environment.observe("external_primary").mediaStoreVersion)
        assertEquals("card-namespace", environment.observe("1234-5678").mediaStoreVersion)
        assertEquals(listOf("external_primary", "1234-5678"), provider.calls)
        assertFalse(environment.observe("missing-volume").volumeMounted)
        assertEquals(2, provider.calls.size)
    }

    @Test fun aRebuiltCardNamespaceInvalidatesItsSourceWithoutInventingAFileDeletion() {
        val (context, provider) = setup()
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        val request = NativeGalleryRequest(receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
        val album = GalleryAlbumCandidate(GallerySourceKind.CAMERA, "1234-5678", "camera-bucket", "Camera", "DCIM/Camera/", 1, false)
        val scope = GalleryPhotoSourceScope({ request }, AndroidGalleryAccessEnvironment(context) { "a".repeat(64) })
        val lease = scope.capture(GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(album), request), album)
        assertTrue(scope.isCurrent(lease))
        provider.versions["1234-5678"] = "rebuilt-card-namespace"
        assertFalse(scope.isCurrent(lease)); assertFalse(lease.provesFileDeletion)
        assertEquals("primary-namespace", AndroidGalleryAccessEnvironment(context) { "a".repeat(64) }.observe("external_primary").mediaStoreVersion)
    }
}
