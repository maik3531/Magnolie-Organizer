package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class NativeGalleryAlbumCatalogTest {
    private class Fixture(size: Int = 1, ambiguous: Boolean = false) {
        val owner = Any()
        var current = true
        var clock = 100L
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        val request = NativeGalleryRequest(receiver, "a".repeat(64), setOf(GallerySourceKind.CAMERA))
        val albums = (0 until size).map { GalleryAlbumCandidate(GallerySourceKind.CAMERA, "external", "private_bucket_$it",
            "相片".repeat(100) + it, "DCIM/private/$it/", 1, ambiguous) }
        val source = GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, albums, request, "b".repeat(64))
        val catalog = NativeGalleryAlbumCatalog(source, owner, { current }, { clock })
    }

    @Test fun boundedPagesKeepOpaqueNativeIdsStableWithoutExposingTechnicalPathsOrDeletionProof() {
        val f = Fixture(AndroidGalleryAlbumDiscovery.MAX_ALBUMS)
        var page = f.catalog.page()
        assertEquals(page, f.catalog.page())
        val id = page.string("catalog_id")
        val ids = mutableSetOf<String>()
        var visited = 0
        while (true) {
            val wire = TelefonKanonisch.bytes(page).decodeToString()
            assertTrue(wire.toByteArray().size <= DeviceFileControl.MAX_WIRE_BYTES - 2048)
            assertFalse(wire.contains("private_bucket")); assertFalse(wire.contains("DCIM/private"))
            assertEquals(JsonPrimitive(false), page["proves_deletion"])
            for (album in page["albums"]!!.jsonArray) {
                assertTrue(ids.add(album.jsonObject.string("album_id"))); visited++
                assertEquals(JsonPrimitive(1), album.jsonObject["visible_images"])
            }
            if (page["next_cursor"] == JsonNull) break
            page = f.catalog.page(id, page["next_cursor"]!!.jsonPrimitive.content.toInt())
        }
        assertEquals(128, visited)
        assertThrows(PhotoFolderScopeError::class.java) { f.catalog.page("wrong-catalog", 1) }
        assertThrows(PhotoFolderScopeError::class.java) { f.catalog.page(after = 1) }
    }

    @Test fun onlyTheExactNativeMappingAndWorkflowOwnerCanResolveAnAlbumSelection() {
        val f = Fixture(); val page = f.catalog.page(); val id = page.string("catalog_id")
        val key = page["albums"]!!.jsonArray.single().jsonObject.string("album_id")
        val selection = f.catalog.select(id, key, false)
        assertSame(f.albums.single(), f.catalog.resolve(f.owner, selection))
        assertThrows(PhotoFolderScopeError::class.java) { f.catalog.select(id, f.albums.single().bucketId, true) }
        assertThrows(PhotoFolderScopeError::class.java) { f.catalog.resolve(Any(), selection) }
        assertThrows(PhotoFolderScopeError::class.java) {
            f.catalog.resolve(f.owner, NativeGalleryAlbumSelection(f.catalog, f.albums.single().copy(), true))
        }
    }

    @Test fun metadataListingDoesNotSupplyTheRequiredExplicitChoiceForAmbiguousAlbums() {
        val f = Fixture(ambiguous = true); val page = f.catalog.page()
        val key = page["albums"]!!.jsonArray.single().jsonObject.string("album_id")
        assertThrows(PhotoFolderScopeError::class.java) { f.catalog.select(page.string("catalog_id"), key, false) }
        assertSame(f.albums.single(), f.catalog.resolve(f.owner, f.catalog.select(page.string("catalog_id"), key, true)))
    }

    @Test fun expiredRevokedClosedOrRewoundCatalogsCannotBeRevivedByMatchingOldTokens() {
        for (reason in listOf("expired", "revoked", "closed", "clock")) {
            val f = Fixture(); val page = f.catalog.page()
            val key = page["albums"]!!.jsonArray.single().jsonObject.string("album_id")
            val selection = f.catalog.select(page.string("catalog_id"), key, true)
            when (reason) {
                "expired" -> f.clock += DeviceFileControl.MAX_TTL_MS
                "revoked" -> f.current = false
                "closed" -> f.catalog.close()
                else -> f.clock--
            }
            assertThrows(PhotoFolderScopeError::class.java) { f.catalog.resolve(f.owner, selection) }
            f.clock = 100; f.current = true
            assertThrows(PhotoFolderScopeError::class.java) { f.catalog.page() }
        }
    }

    @Test fun emptyCatalogHasNoSelectionAndNeverProvesAFileWasDeleted() {
        val f = Fixture(size = 0); val page = f.catalog.page()
        assertEquals(JsonNull, page["next_cursor"]); assertTrue(page["albums"]!!.jsonArray.isEmpty())
        assertEquals(JsonPrimitive(false), page["proves_deletion"])
        assertThrows(PhotoFolderScopeError::class.java) { f.catalog.select(page.string("catalog_id"), "made-up-album", true) }
    }

    @Test fun admittedAlbumContinuationMustNotDependOnExpiredMetadata() {
        val f = Fixture(); val page = f.catalog.page()
        val key = page["albums"]!!.jsonArray.single().jsonObject.string("album_id")
        val selection = f.catalog.select(page.string("catalog_id"), key, false)
        val retained = NativeGalleryAlbumLease(f.owner, selection)
        assertSame(f.albums.single(), retained.resolve(f.owner))
        f.clock += DeviceFileControl.MAX_TTL_MS + 1
        assertThrows(PhotoFolderScopeError::class.java) { f.catalog.resolve(f.owner, selection) }
        assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryAlbumLease(f.owner, selection) }
        assertThrows(PhotoFolderScopeError::class.java) { f.catalog.select(page.string("catalog_id"), key, false) }
        assertSame(f.albums.single(), retained.resolve(f.owner))
        retained.close()
        assertThrows(PhotoFolderScopeError::class.java) { retained.resolve(f.owner) }
    }

    @Test fun retainedAlbumAuthorityCannotReviveAfterRevocationCloseOrClockRewind() {
        for (reason in listOf("revoked", "catalog_closed", "lease_closed", "clock", "metadata_clock")) {
            val f = Fixture(); val page = f.catalog.page()
            val selection = f.catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), false)
            val retained = NativeGalleryAlbumLease(f.owner, selection)
            f.clock += DeviceFileControl.MAX_TTL_MS + 1
            if (reason == "metadata_clock") assertThrows(PhotoFolderScopeError::class.java) { f.catalog.page() }
            else assertSame(f.albums.single(), retained.resolve(f.owner))
            when (reason) {
                "revoked" -> f.current = false
                "catalog_closed" -> f.catalog.close()
                "lease_closed" -> retained.close()
                else -> f.clock--
            }
            assertThrows(PhotoFolderScopeError::class.java) { retained.resolve(f.owner) }
            f.current = true; f.clock += 2
            assertThrows(PhotoFolderScopeError::class.java) { retained.resolve(f.owner) }
        }
    }

    @Test fun retainedAlbumRequiresExactOwnerReferenceAndBoundedLiveAdmission() {
        val f = Fixture(); val page = f.catalog.page()
        val selection = f.catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), false)
        assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryAlbumLease(Any(), selection) }
        assertThrows(PhotoFolderScopeError::class.java) {
            NativeGalleryAlbumLease(f.owner, NativeGalleryAlbumSelection(f.catalog, f.albums.single().copy(), false))
        }
        val leases = (1..4).map { NativeGalleryAlbumLease(f.owner, selection) }
        assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryAlbumLease(f.owner, selection) }
        assertThrows(PhotoFolderScopeError::class.java) { leases.first().resolve(Any()) }
        val other = Fixture()
        assertThrows(PhotoFolderScopeError::class.java) { other.catalog.resolveRetained(other.owner, leases.first()) }
        assertSame(f.albums.single(), leases.first().resolve(f.owner))
        leases.first().close()
        NativeGalleryAlbumLease(f.owner, selection).use { assertSame(f.albums.single(), it.resolve(f.owner)) }
        leases.forEach { it.close() }
    }

    @Test fun nativeFreshnessCallbackCannotReturnMetadataAfterItsReadCrossesTheDeadlineOrRewindsTheClock() {
        for (rewind in listOf(false, true)) {
            val f = Fixture(); var clock = 100L
            val catalog = NativeGalleryAlbumCatalog(f.source, f.owner, {
                clock = if (rewind) 99 else 100 + DeviceFileControl.MAX_TTL_MS
                true
            }, { clock })
            assertThrows(PhotoFolderScopeError::class.java) { catalog.page() }
            clock = 100
            assertThrows(PhotoFolderScopeError::class.java) { catalog.page() }
        }
    }
}
