package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class NativeGalleryPermissionActionsTest {
    private class Fixture {
        var owner: Any = Any()
        var request: NativeGalleryRequest? = NativeGalleryRequest(NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(),
            "f".repeat(64), true, true, true, true, true, true, 1, "1".repeat(64)), "b".repeat(64), setOf(GallerySourceKind.CAMERA))
        var now = 100L
        var failRead = false
        val actions = NativeGalleryPermissionActions({
            if (failRead) throw IOException("synthetic protected authority read")
            request?.let { NativeGalleryPermissionActionScope(owner, it) }
        }, { now })
    }

    @Test fun explicitNativeActionIsBoundedIdempotentAndConsumedOnlyAfterLaunch() {
        val f = Fixture(); val action = f.actions.create(); var launches = 0
        assertTrue(DeviceFileControl.hash(action.token)); assertSame(action, f.actions.create())
        assertThrows(PhotoFolderScopeError::class.java) { f.actions.perform("0".repeat(64)) { launches++ } }
        assertTrue(f.actions.isCurrent(action.token)); assertEquals(0, launches)
        f.actions.perform(action.token) { assertSame(f.owner, it); launches++ }
        assertEquals(1, launches); assertFalse(f.actions.isCurrent(action.token))
        assertThrows(PhotoFolderScopeError::class.java) { f.actions.perform(action.token) { launches++ } }
        assertEquals(1, launches)
    }

    @Test fun foregroundWaitKeepsNativeActionButExpiryCannotBeExtendedOrRewound() {
        val f = Fixture(); val action = f.actions.create()
        assertThrows(PhotoFolderScopeError::class.java) { f.actions.perform(action.token) { throw PhotoFolderScopeError("gallery_permission_foreground_required") } }
        assertTrue(f.actions.isCurrent(action.token))
        f.now += DeviceFileControl.MAX_TTL_MS - 1
        assertSame(action, f.actions.create())
        f.now++
        assertFalse(f.actions.isCurrent(action.token))
        f.now = 100
        assertFalse(f.actions.isCurrent(action.token))
        assertNotEquals(action.token, f.actions.create().token)
    }

    @Test fun ownerSourceIdentityConsentPairingAndSelectionChangesInvalidateOldUiAction() {
        for (change in listOf("owner", "receiver-owner", "peer", "key", "grant", "pairing", "policy", "kinds", "disabled")) {
            val f = Fixture(); val action = f.actions.create(); val old = f.request!!
            f.request = when (change) {
                "receiver-owner" -> NativeGalleryRequest(old.receiver.copy(owner = Any()), old.policyEpoch, old.kinds)
                "peer" -> NativeGalleryRequest(old.receiver.copy(peerId = "another_receiver_01"), old.policyEpoch, old.kinds)
                "key" -> NativeGalleryRequest(old.receiver.copy(identitySha256 = "c".repeat(64)), old.policyEpoch, old.kinds)
                "grant" -> NativeGalleryRequest(old.receiver.copy(permissionEpoch = "c".repeat(64)), old.policyEpoch, old.kinds)
                "pairing" -> NativeGalleryRequest(old.receiver.copy(pairingEpoch = "2".repeat(64)), old.policyEpoch, old.kinds)
                "policy" -> NativeGalleryRequest(old.receiver, "c".repeat(64), old.kinds)
                "kinds" -> NativeGalleryRequest(old.receiver, old.policyEpoch, setOf(GallerySourceKind.SCREENSHOTS))
                "disabled" -> null
                else -> { f.owner = Any(); old }
            }
            var launches = 0
            assertFalse(f.actions.isCurrent(action.token))
            assertThrows(PhotoFolderScopeError::class.java) { f.actions.perform(action.token) { launches++ } }
            assertEquals(0, launches)
            f.request = old
            assertFalse(f.actions.isCurrent(action.token))
        }
    }

    @Test fun exactNativeOwnerCancellationCannotCancelAnUnrelatedAction() {
        val f = Fixture(); val action = f.actions.create()
        f.actions.cancelOwner(Any()); assertTrue(f.actions.isCurrent(action.token))
        f.actions.cancelOwner(f.owner); assertFalse(f.actions.isCurrent(action.token))
    }

    @Test fun uncertainNativeReadOrNonRetryableLaunchDoesNotRestoreActionAfterRepair() {
        val f = Fixture(); val first = f.actions.create()
        f.failRead = true
        assertThrows(IOException::class.java) { f.actions.create() }
        f.failRead = false
        assertFalse(f.actions.isCurrent(first.token))
        val second = f.actions.create()
        assertThrows(IOException::class.java) { f.actions.perform(second.token) { throw IOException("native launch failed") } }
        assertFalse(f.actions.isCurrent(second.token))
    }

    @Test fun absenceOrUnapprovedSourceCannotCreateAnActionOrInventAFileGrant() {
        val f = Fixture(); f.request = null
        assertThrows(PhotoFolderScopeError::class.java) { f.actions.create() }
        val off = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, false, true, 1)
        f.request = NativeGalleryRequest(off, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
        assertThrows(PhotoFolderScopeError::class.java) { f.actions.create() }
        assertFalse(f.actions.isCurrent("native-name-not-a-ticket"))
    }

    @Test fun sameNativeOwnerAndEpochCannotReassignAnImageActionToVideo() {
        val f = Fixture(); val old = f.request!!; val image = f.actions.create()
        assertEquals(GalleryMediaType.IMAGES, image.mediaType)
        f.request = NativeGalleryRequest(old.receiver, old.policyEpoch, old.kinds, GalleryMediaType.VIDEO)
        assertFalse(f.actions.isCurrent(image.token))
        var launches = 0
        assertThrows(PhotoFolderScopeError::class.java) { f.actions.perform(image.token) { launches++ } }
        val video = f.actions.create()
        assertEquals(GalleryMediaType.VIDEO, video.mediaType); assertNotEquals(image.token, video.token)
        f.request = old
        assertFalse(f.actions.isCurrent(video.token)); assertEquals(0, launches)
    }
}
