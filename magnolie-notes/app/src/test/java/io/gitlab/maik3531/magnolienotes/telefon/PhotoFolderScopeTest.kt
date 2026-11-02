package io.gitlab.maik3531.magnolienotes.telefon

import java.io.IOException
import org.junit.Assert.*
import org.junit.Test

class PhotoFolderScopeTest {
    private class EqualOwner {
        override fun equals(other: Any?) = true
        override fun hashCode() = 0
    }
    private class Trees : ReadOnlyPhotoTrees {
        val grants = mutableMapOf(BACKUP to "b".repeat(64))
        val writeGrants = mutableSetOf(BACKUP)
        val requests = mutableListOf<String>()
        var deny = false
        private var sequence = 0
        override fun canonicalTree(uri: String): String = uri.takeIf { it in setOf(ONE, TWO, BACKUP) }
            ?: throw PhotoFolderScopeError("invalid_photo_tree")
        override fun persistRead(uri: String) {
            if (deny) throw IOException("synthetic permission refusal")
            requests += canonicalTree(uri); grants[uri] = (++sequence).toString(16).padStart(64, '0')
        }
        override fun readGrantToken(uri: String) = grants[canonicalTree(uri)]
    }
    private class Store : PhotoFolderPreferenceStore {
        var state = PhotoPreferenceSnapshot("0".repeat(64), null)
        var writes = 0
        var reads = 0
        var beforePublish: (() -> Unit)? = null
        var afterRead: ((Int) -> Unit)? = null
        var failAfterPublish = false
        override fun read(): PhotoPreferenceSnapshot {
            val observed = state; reads++; afterRead?.invoke(reads); return observed
        }
        override fun compareAndSet(expected: PhotoPreferenceSnapshot, next: PhotoFolderPreference, permitted: () -> Boolean): PhotoPreferenceSnapshot {
            if (state != expected || state.repairPending) throw PhotoFolderScopeError("synthetic_native_cas_conflict")
            if (!permitted()) throw PhotoFolderScopeError("synthetic_source_revoked")
            state = state.copy(repairPending = true) // Models the REQUIRED durable native repair fence.
            beforePublish?.invoke()
            if (!permitted()) throw PhotoFolderScopeError("synthetic_source_revoked_at_publication")
            state = PhotoPreferenceSnapshot((++writes).toString(16).padStart(64, '0'), next)
            if (failAfterPublish) {
                state = state.copy(repairPending = true)
                throw IOException("synthetic acknowledgement failure after native publication")
            }
            return state
        }
    }
    private class Fixture {
        val owner = EqualOwner()
        var receiver: NativePhotoReceiver? = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), owner, "f".repeat(64),
            ready = true, paired = true, ownDevice = true, remoteOwnDevice = true, sendGranted = true, receiveGranted = true, manifestVersion = 1)
        val trees = Trees(); val store = Store(); var sequence = 0
        val scope = PhotoFolderScope({ receiver }, trees, store) { (++sequence).toString(16).padStart(64, '0') }
        fun choose(uri: String = ONE) { assertTrue(scope.completePicker(scope.beginPicker(), uri)) }
        fun enable(): PhotoFolderLease { choose(); scope.setEnabled(true); return requireNotNull(scope.lease()) }
    }

    @Test fun explicitSelectionStartsOffAndNeverReleasesOtherFeaturesReadOrWriteRights() {
        val f = Fixture()
        assertNull(f.scope.lease())
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.setEnabled(true) }
        val canceled = f.scope.beginPicker()
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.beginPicker() }
        assertFalse(f.scope.completePicker(canceled, null))
        assertEquals(0, f.store.writes); assertTrue(f.trees.requests.isEmpty())
        f.choose()
        assertFalse(f.store.state.preference!!.enabled); assertNull(f.scope.lease())
        assertEquals(listOf(ONE), f.trees.requests)
        val selectedEpoch = f.store.state.preference!!.epoch
        f.scope.setEnabled(true)
        val lease = requireNotNull(f.scope.lease())
        assertNotEquals(selectedEpoch, lease.preference.epoch)
        f.receiver = f.receiver!!.copy() // Ordinary view/book refresh, same native lifecycle owner.
        assertTrue(f.scope.isCurrent(lease))
        f.receiver = null // Local revocation must still be possible with the peer gone.
        f.scope.setEnabled(false)
        assertFalse(f.store.state.preference!!.enabled)
        assertEquals(setOf(BACKUP), f.trees.writeGrants)
        assertTrue(BACKUP in f.trees.grants && ONE in f.trees.grants)
        assertNull(f.scope.lease())
    }

    @Test fun pickerResultCannotMoveToAnotherPeerKeyOwnerOrGrantEpoch() {
        val changes: List<(NativePhotoReceiver) -> NativePhotoReceiver> = listOf(
            { it.copy(peerId = "another_receiver_01") }, { it.copy(identitySha256 = "1".repeat(64)) },
            { it.copy(owner = EqualOwner()) }, { it.copy(permissionEpoch = "1".repeat(64)) },
            { it.copy(ready = false) }, { it.copy(paired = false) }, { it.copy(ownDevice = false) },
            { it.copy(remoteOwnDevice = false) }, { it.copy(sendGranted = false) },
            { it.copy(receiveGranted = false) }, { it.copy(manifestVersion = 0) })
        for (change in changes) {
            val f = Fixture(); val ticket = f.scope.beginPicker(); f.receiver = change(f.receiver!!)
            assertThrows(PhotoFolderScopeError::class.java) { f.scope.completePicker(ticket, ONE) }
            assertNull(f.store.state.preference); assertTrue(f.trees.requests.isEmpty())
            assertNull(f.scope.lease())
        }
    }

    @Test fun copiedCanceledOrLatePickerTicketsDoNotAuthorizeASelection() {
        val f = Fixture(); val ticket = f.scope.beginPicker()
        val forged = PhotoFolderPickerTicket(ticket.receiver, ticket.expected)
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.completePicker(forged, ONE) }
        f.scope.cancelPicker(ticket)
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.completePicker(ticket, ONE) }
        assertTrue(f.trees.requests.isEmpty()); assertEquals(0, f.store.writes)
        val active = f.enable()
        val pending = f.scope.beginPicker()
        assertFalse(f.scope.isCurrent(active))
        f.scope.cancelPicker(pending)
        assertTrue(f.scope.isCurrent(active))
    }

    @Test fun concurrentDedicatedPreferenceChangesAreNotBlindlyOverwritten() {
        val f = Fixture(); val ticket = f.scope.beginPicker()
        val concurrent = PhotoPreferenceSnapshot("9".repeat(64), PhotoFolderPreference(TWO, "receiver_fixture_01", "e".repeat(64), "8".repeat(64), true))
        f.store.state = concurrent
        f.trees.grants[TWO] = "7".repeat(64)
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.completePicker(ticket, ONE) }
        assertEquals(concurrent, f.store.state)
        assertNull(f.scope.lease())
    }

    @Test fun revocationAtActualPreferencePublicationKeepsTheOriginalAndDurableFence() {
        for (permission in listOf(false, true)) {
            val f = Fixture(); f.choose(); val before = f.store.state.preference
            f.store.beforePublish = {
                if (permission) f.trees.grants.remove(ONE) else f.receiver = f.receiver!!.copy(ready = false)
            }
            assertThrows(PhotoFolderScopeError::class.java) { f.scope.setEnabled(true) }
            assertEquals(before, f.store.state.preference); assertTrue(f.store.state.repairPending)
            f.receiver = f.receiver!!.copy(ready = true)
            f.trees.grants[ONE] = "6".repeat(64)
            assertNull(f.scope.lease())
            assertNull(PhotoFolderScope({ f.receiver }, f.trees, f.store).lease())
        }
    }

    @Test fun aLeaseIsBoundToCurrentNativeOwnerPermissionReadGrantAndDedicatedPreferenceVersion() {
        val changes: List<(Fixture) -> Unit> = listOf(
            { it.receiver = it.receiver!!.copy(owner = EqualOwner()) },
            { it.receiver = it.receiver!!.copy(identitySha256 = "1".repeat(64)) },
            { it.receiver = it.receiver!!.copy(permissionEpoch = "1".repeat(64)) },
            { it.receiver = it.receiver!!.copy(ready = false) },
            { it.receiver = it.receiver!!.copy(receiveGranted = false) },
            { it.trees.grants.remove(ONE) }, { it.trees.grants[ONE] = "5".repeat(64) },
            { it.store.state = it.store.state.copy(version = "4".repeat(64)) },
            { it.store.state = it.store.state.copy(repairPending = true) })
        for (change in changes) {
            val f = Fixture(); val lease = f.enable(); change(f)
            assertFalse(f.scope.isCurrent(lease))
        }
    }

    @Test fun leaseCreationRechecksTheActualDedicatedStateAfterCapturingAuthority() {
        val f = Fixture(); f.enable(); f.store.reads = 0
        f.store.afterRead = { count -> if (count == 1) f.store.state = f.store.state.copy(version = "2".repeat(64)) }
        assertNull(f.scope.lease())
    }

    @Test fun uncertainAppliedWritesRemainFencedAcrossARecreatedScope() {
        val f = Fixture(); f.choose(); f.store.failAfterPublish = true
        assertThrows(IOException::class.java) { f.scope.setEnabled(true) }
        assertTrue(f.store.state.preference!!.enabled && f.store.state.repairPending)
        assertNull(f.scope.lease())
        assertNull(PhotoFolderScope({ f.receiver }, f.trees, f.store).lease())
    }

    @Test fun deniedOrNonTreePickerResultsPreserveThePreviouslyEnabledSource() {
        val f = Fixture(); val lease = f.enable(); val original = f.store.state
        val malformed = f.scope.beginPicker()
        assertThrows(PhotoFolderScopeError::class.java) { f.scope.completePicker(malformed, "file:///arbitrary") }
        assertEquals(original, f.store.state); assertTrue(f.scope.isCurrent(lease))
        f.trees.deny = true
        val denied = f.scope.beginPicker()
        assertThrows(IOException::class.java) { f.scope.completePicker(denied, TWO) }
        assertEquals(original, f.store.state); assertTrue(f.scope.isCurrent(lease))
        assertEquals(setOf(BACKUP), f.trees.writeGrants)
    }

    companion object {
        private const val ONE = "content://fixture.documents/tree/one"
        private const val TWO = "content://fixture.documents/tree/two"
        private const val BACKUP = "content://fixture.documents/tree/existing-backup"
    }
}
