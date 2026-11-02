package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.os.CancellationSignal
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.ByteArrayInputStream
import java.io.File
import java.nio.file.Files
import javax.crypto.spec.SecretKeySpec
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class GalleryPhotoSourceScopeTest {
    private class Environment : GalleryAccessEnvironment {
        var value = GalleryAccessObservation(GalleryReadCoverage.FULL_IMAGES, "a".repeat(64), "native-store-v1", true)
        override fun observe(volume: String) = value
    }
    private class Fixture {
        var request: NativeGalleryRequest? = NativeGalleryRequest(NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(),
            "f".repeat(64), true, true, true, true, true, true, 1), "b".repeat(64), setOf(GallerySourceKind.WHATSAPP_RECEIVED))
        val environment = Environment()
        val album = GalleryAlbumCandidate(GallerySourceKind.WHATSAPP_RECEIVED, "external", "whatsapp-bucket", "WhatsApp Images", null, 1, false)
        val scope = GalleryPhotoSourceScope({ request }, environment)
        fun catalog(value: GalleryAlbumCandidate = album) = GalleryAlbumCatalog(environment.value.coverage, listOf(value), request)
        fun lease() = scope.capture(catalog(), album)
    }

    @Test fun aCatalogBoundToAnOlderNativeAccessEpochCannotAuthorizeNewPhotoSelection() {
        val f = Fixture()
        val catalog = GalleryAlbumCatalog(f.environment.value.coverage, listOf(f.album), f.request, f.environment.value.accessEpoch)
        assertTrue(f.scope.isCurrent(f.scope.capture(catalog, f.album)))
        f.environment.value = f.environment.value.copy(accessEpoch = "c".repeat(64))
        assertEquals("gallery_source_visibility_changed", assertThrows(PhotoFolderScopeError::class.java) { f.scope.capture(catalog, f.album) }.code)
    }

    @Test fun onlyAnActualActivatedCatalogMemberCanBecomeANativeGalleryLease() {
        val f = Fixture(); val catalog = f.catalog()
        val lease = f.scope.capture(catalog, f.album)
        assertTrue(lease.sourceKey.startsWith("gallery-album-v1:")); assertFalse(lease.sourceKey.startsWith("content://"))
        assertTrue(f.scope.isCurrent(lease)); assertFalse(lease.provesFileDeletion)
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.capture(catalog, f.album.copy()) }
        val ambiguous = f.album.copy(needsAlbumChoice = true)
        val choices = f.catalog(ambiguous)
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.capture(choices, ambiguous) }
        assertTrue(f.scope.isCurrent(f.scope.capture(choices, ambiguous, desktopAlbumChoice = true)))
        f.request = null
        assertFalse(f.scope.isCurrent(lease))
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.capture(catalog, f.album) }
    }

    @Test fun changedPermissionSubsetStoreNamespaceVolumeOrPolicyInvalidatesOldProofs() {
        val changes: List<(Fixture) -> Unit> = listOf(
            { it.environment.value = it.environment.value.copy(coverage = GalleryReadCoverage.NONE) },
            { it.environment.value = it.environment.value.copy(coverage = GalleryReadCoverage.SELECTED_ONLY) },
            { it.environment.value = it.environment.value.copy(accessEpoch = "c".repeat(64)) },
            { it.environment.value = it.environment.value.copy(mediaStoreVersion = "rebuilt-media-store") },
            { it.environment.value = it.environment.value.copy(volumeMounted = false) },
            { it.request = NativeGalleryRequest(it.request!!.receiver.copy(owner = Any()), "b".repeat(64), it.request!!.kinds) },
            { it.request = NativeGalleryRequest(it.request!!.receiver.copy(identitySha256 = "c".repeat(64)), "b".repeat(64), it.request!!.kinds) },
            { it.request = NativeGalleryRequest(it.request!!.receiver.copy(permissionEpoch = "c".repeat(64)), "b".repeat(64), it.request!!.kinds) },
            { it.request = NativeGalleryRequest(it.request!!.receiver.copy(receiveGranted = false), "b".repeat(64), it.request!!.kinds) },
            { it.request = NativeGalleryRequest(it.request!!.receiver, "c".repeat(64), it.request!!.kinds) },
            { it.request = NativeGalleryRequest(it.request!!.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA)) })
        changes.forEach { change -> val f = Fixture(); val lease = f.lease(); change(f); assertFalse(f.scope.isCurrent(lease)) }
    }

    @Test fun unknownLegacyNamespacesAndSelectedOnlyAccessNeverReuseOldRuntimeProofsAcrossRecreation() {
        for (limited in listOf(false, true)) {
            val f = Fixture()
            f.environment.value = if (limited) f.environment.value.copy(coverage = GalleryReadCoverage.SELECTED_ONLY)
                else f.environment.value.copy(mediaStoreVersion = null)
            val lease = f.lease()
            assertEquals(lease.readGrantToken, f.lease().readGrantToken)
            val recreated = GalleryPhotoSourceScope({ f.request }, f.environment)
            val fresh = recreated.capture(f.catalog(), f.album)
            assertNotEquals(lease.readGrantToken, fresh.readGrantToken)
            assertFalse(recreated.isCurrent(lease)); assertFalse(f.scope.isCurrent(fresh))
            assertFalse(fresh.provesFileDeletion)
        }
    }

    @Test fun realLegacyOsAccessObservationDoesNotInventAPersistentMediaNamespaceOrPhotoPermission() {
        val context = RuntimeEnvironment.getApplication()
        val shadow = Shadows.shadowOf(context as Application)
        shadow.grantPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
        val environment = AndroidGalleryAccessEnvironment(context) { "a".repeat(64) }
        assertEquals(GalleryAccessObservation(GalleryReadCoverage.FULL_IMAGES, "a".repeat(64), null, true), environment.observe("external"))
        assertFalse(environment.observe("unmounted-volume").volumeMounted)
        shadow.denyPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
        assertEquals(GalleryReadCoverage.NONE, environment.observe("external").coverage)
        assertFalse(environment.observe("external").volumeMounted)
    }

    @Test fun galleryAndSafAuthoritiesCannotBeSubstitutedForEachOther() {
        val f = Fixture(); val gallery = f.lease()
        val saf = AndroidPhotoFolderInventoryTest.Fixture()
        assertFalse(saf.scope.isCurrent(gallery)); assertFalse(f.scope.isCurrent(saf.lease))
        val reader = AndroidPhotoSourceReader(saf.context, saf.scope)
        assertThrows(PhotoFolderScopeError::class.java) { reader.openRead(gallery,
            PhotoInventoryEntry("content://media/external/images/media/1", "1", "image.jpg", 5, 100), CancellationSignal()) }
    }

    @Test fun typedGalleryLeaseUsesTheActualProtectedSnapshotIndexPathWithoutASyntheticSafUri() {
        val f = Fixture(); val lease = f.lease()
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "gallery-snapshot329-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val inventory = PhotoSourceInventory(lease, listOf(PhotoInventoryEntry("content://media/external/images/media/1", "1:90", "image.jpg", 5, 100)))
        val source = object : PhotoSourceAccess {
            override fun verifyMetadata(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal) { check(f.scope.isCurrent(lease)) }
            override fun openRead(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal) = ByteArrayInputStream("hello".toByteArray())
        }
        try {
            val job: PhotoSourceJob
            PhotoSourceJobIndex(root, protection).use { index ->
                val reserved = index.reserve(inventory, f.scope)
                val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, "sender_fixture_01", f.scope, source, protection)
                job = index.publishSnapshot(reserved, snapshot, f.scope, lease)
            }
            val recreated = GalleryPhotoSourceScope({ f.request }, f.environment)
            val fresh = recreated.capture(f.catalog(), f.album)
            assertEquals(lease.version, fresh.version) // Reliable unchanged full namespace, but fresh native scope ownership.
            PhotoSourceJobIndex(root, protection).use { index ->
                val restored = index.restore(job, "sender_fixture_01", recreated, fresh)
                assertArrayEquals("hello".toByteArray(), restored.readChunk(restored.manifest.files.single().id, 0))
                assertEquals(JsonPrimitive(2), job.snapshot!!["format"])
                val origins = restored.galleryOrigins!!
                assertEquals(restored.manifest.files.single().id, origins.entries.single().fileId)
                assertEquals("1:90", origins.entries.single().nativeMember)
                val legacyRecord = JsonObject(job.snapshot.minus("source_origins") + ("format" to JsonPrimitive(1)))
                val legacy = ProtectedPhotoSourceSnapshot.restore(index.rootFile(job), legacyRecord, "sender_fixture_01", recreated,
                    fresh, protection, CancellationSignal())
                assertNull(legacy.galleryOrigins) // Never invent legacy photo identities from filenames.
                assertEquals(JsonPrimitive(1), legacy.nativeRecord()["format"])
                assertArrayEquals("hello".toByteArray(), legacy.readChunk(legacy.manifest.files.single().id, 0))
                restored.retireAndDiscard(); assertTrue(index.jobs().isEmpty())
                assertThrows(PhotoFolderScopeError::class.java) { restored.galleryOrigins }
            }
        } finally { root.deleteRecursively() }
    }
}
