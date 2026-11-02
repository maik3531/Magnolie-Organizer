package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class GalleryPhotoOriginsTest {
    private fun lease(namespace: String? = "native-store-v1", epoch: String = "a".repeat(64),
        policy: String = "b".repeat(64), bucket: String = "camera", coverage: GalleryReadCoverage = GalleryReadCoverage.FULL_IMAGES): GalleryPhotoSourceLease {
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        val request = NativeGalleryRequest(receiver, policy, setOf(GallerySourceKind.CAMERA))
        val album = GalleryAlbumCandidate(GallerySourceKind.CAMERA, "external", bucket, "Camera", null, 1, false)
        val environment = object : GalleryAccessEnvironment {
            override fun observe(volume: String) = GalleryAccessObservation(coverage, epoch, namespace, true)
        }
        return GalleryPhotoSourceScope({ request }, environment).capture(GalleryAlbumCatalog(coverage, listOf(album), request), album)
    }
    private fun manifest(path: String = "image.jpg", id: String = "c".repeat(32), size: Long = 5,
        sender: String = "sender_fixture_01"): DeviceFileManifest {
        val original = Json.parseToJsonElement(File("../contracts/file-transfer-manifest-v1-vectors.json").readText())
            .jsonObject["vectors"]!!.jsonArray.first().jsonObject["manifest"]!!.jsonObject
        val member = original["files"]!!.jsonArray.single().jsonObject
        return DeviceFileManifest.parse(JsonObject(original + mapOf("sender_id" to JsonPrimitive(sender), "total_bytes" to JsonPrimitive(size),
            "files" to JsonArray(listOf(JsonObject(member + mapOf("id" to JsonPrimitive(id), "path" to JsonPrimitive(path), "size" to JsonPrimitive(size))))))))
    }
    private fun entry(path: String = "image.jpg", size: Long = 5, member: String = "1:90") =
        PhotoInventoryEntry("content://media/external/images/media/${member.substringBefore(':')}", member, path, size, 100000)

    @Test fun privateOriginCorrelationSurvivesEditsRenamesAndNativeAccessRefreshButIsNotAPermissionOrReceipt() {
        val first = GalleryPhotoOrigins.capture(lease(), listOf(entry()), manifest())
        val changed = GalleryPhotoOrigins.capture(lease(epoch = "d".repeat(64), policy = "c".repeat(64)),
            listOf(entry("cropped.jpg", 3)), manifest("cropped.jpg", "d".repeat(32), 3))
        assertEquals(first.entries.single().photoId, changed.entries.single().photoId)
        assertNotEquals(first.entries.single().fileId, changed.entries.single().fileId)
        assertEquals("1:90", first.entries.single().nativeMember)
        assertFalse(first.provesMutationIdentity)
        assertThrows(UnsupportedOperationException::class.java) { (first.entries as MutableList<GalleryPhotoOrigin>).clear() }
    }

    @Test fun senderAlbumVolumeNamespaceAndInsertedRowWitnessPreventCrossSourceCorrelation() {
        val original = GalleryPhotoOrigins.capture(lease(), listOf(entry()), manifest()).entries.single().photoId
        val changed = listOf(
            GalleryPhotoOrigins.capture(lease(namespace = "rebuilt-store"), listOf(entry()), manifest()),
            GalleryPhotoOrigins.capture(lease(bucket = "another-camera"), listOf(entry()), manifest()),
            GalleryPhotoOrigins.capture(lease(), listOf(entry(member = "1:91")), manifest()),
            GalleryPhotoOrigins.capture(lease(), listOf(entry(member = "2:90")), manifest()),
            GalleryPhotoOrigins.capture(lease(), listOf(entry()), manifest(sender = "another_sender_01")))
        assertTrue(changed.all { it.entries.single().photoId != original })
        assertNotEquals(GalleryPhotoOrigins.capture(lease(namespace = null), listOf(entry()), manifest()).entries.single().photoId,
            GalleryPhotoOrigins.capture(lease(namespace = null), listOf(entry()), manifest()).entries.single().photoId)
        // A known provider namespace may correlate selected visible members,
        // but selected-only catalogs/leases still never prove any deletion.
        val selected = lease(coverage = GalleryReadCoverage.SELECTED_ONLY)
        assertEquals(original, GalleryPhotoOrigins.capture(selected, listOf(entry()), manifest()).entries.single().photoId)
        assertFalse(selected.provesFileDeletion)
    }

    @Test fun strictNativeMemberAndManifestAlignmentRejectForgedUriMetadataAndAliases() {
        val lease = lease(); val manifest = manifest()
        for (invalid in listOf(entry(member = "01:90"), entry(member = "1:090"), entry(member = "0:90"),
            entry(member = "9223372036854775808:90"), entry().copy(documentUri = "content://foreign/images/media/1"),
            entry("other.jpg"), entry(size = 4)))
            assertEquals("gallery_photo_origin_invalid", assertThrows(PhotoFolderScopeError::class.java) {
                GalleryPhotoOrigins.capture(lease, listOf(invalid), manifest) }.code)
        assertThrows(PhotoFolderScopeError::class.java) { GalleryPhotoOrigins.capture(lease, emptyList(), manifest) }
    }

    @Test fun restoredOriginRecordsAreExactOrderedAndReboundToActualNativeSourceContext() {
        val lease = lease(); val manifest = manifest()
        val origin = GalleryPhotoOrigins.capture(lease, listOf(entry()), manifest)
        val record = origin.wire()
        assertEquals(origin.entries, GalleryPhotoOrigins.parse(record, manifest, lease).entries)
        assertThrows(PhotoFolderScopeError::class.java) { GalleryPhotoOrigins.parse(record, manifest, lease(namespace = "rebuilt-store")) }
        for ((field, value) in listOf("photo_id" to JsonPrimitive("0".repeat(64)), "native_member" to JsonPrimitive(false),
            "file_id" to JsonPrimitive("d".repeat(32)), "extra" to JsonPrimitive(true))) {
            val changed = JsonObject(record + ("entries" to JsonArray(listOf(JsonObject(record["entries"]!!.jsonArray.single().jsonObject + (field to value))))))
            assertThrows(PhotoFolderScopeError::class.java) { GalleryPhotoOrigins.parse(changed, manifest, lease) }
        }
        assertThrows(PhotoFolderScopeError::class.java) { GalleryPhotoOrigins.parse(JsonObject(record + ("extra" to JsonPrimitive(true))), manifest, lease) }
    }
}
