package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

class ProtectedPhotoFolderPreferencesTest {
    private class Fixture : AutoCloseable {
        val root = Files.createTempDirectory("magnolie-photo-source329-").toFile()
        var key: SecretKey? = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        val protection = DeviceTransferProtection.fromExistingKeyReader { key }
        val state = File(root, "photo-source.enc")
        val fence = File(root, "photo-source-repair.enc")
        fun store(hook: (String) -> Unit = {}) = ProtectedPhotoFolderPreferences(root, protection, hook)
        override fun close() { root.deleteRecursively() }
    }
    private fun preference(enabled: Boolean = false, epoch: Char = 'a') = PhotoFolderPreference(
        "content://fixture.documents/tree/photos", "receiver_fixture_01", "e".repeat(64), epoch.toString().repeat(64), enabled)

    @Test fun realCiphertextCasReadbackSurvivesRecreationAndDoesNotExposeTheTree(): Unit = Fixture().use { f ->
        val store = f.store(); val absent = store.read()
        assertNull(absent.preference); assertFalse(absent.repairPending)
        val saved = store.compareAndSet(absent, preference()) { true }
        assertEquals(preference(), saved.preference)
        assertEquals(saved, f.store().read()); assertFalse(f.fence.exists())
        assertFalse(f.state.readBytes().toString(Charsets.ISO_8859_1).contains("fixture.documents"))
        assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(f.state.toPath()))
        val before = f.state.readBytes()
        assertThrows(PhotoFolderScopeError::class.java) { f.store().compareAndSet(absent, preference(true)) { true } }
        assertArrayEquals(before, f.state.readBytes())
    }

    @Test fun keyLossAndCorruptionAreNeverInterpretedAsAbsentOrReset(): Unit = Fixture().use { f ->
        val store = f.store(); store.compareAndSet(store.read(), preference()) { true }
        val original = f.state.readBytes(); val key = f.key
        f.key = null
        assertThrows(DeviceTransferKeyUnavailable::class.java) { f.store().read() }
        assertArrayEquals(original, f.state.readBytes()); assertNull(f.key)
        f.key = key
        f.state.writeBytes(original.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
        assertThrows(Exception::class.java) { f.store().read() }
        assertTrue(f.state.exists()); assertFalse(f.fence.exists())
    }

    @Test fun everyUncertainPublicationRemainsDurablyFencedAndNeedsExplicitObservedRepair() {
        for (point in listOf("fenced", "before-publication", "published", "before-fence-clear")) Fixture().use { f ->
            val initial = f.store(); val before = initial.compareAndSet(initial.read(), preference()) { true }
            val original = f.state.readBytes()
            val failing = f.store { if (it == point) throw IOException("synthetic boundary failure") }
            assertThrows(IOException::class.java) { failing.compareAndSet(before, preference(true, 'b')) { true } }
            val reopened = f.store(); assertTrue(reopened.read().repairPending)
            assertThrows(PhotoFolderScopeError::class.java) { reopened.compareAndSet(reopened.read(), preference()) { true } }
            val inspection = reopened.inspectRepair()
            assertEquals(point in listOf("published", "before-fence-clear"), inspection.matchesWanted)
            if (!inspection.matchesWanted) assertArrayEquals(original, f.state.readBytes())
            assertThrows(PhotoFolderScopeError::class.java) { reopened.acknowledgeRepair(inspection) { false } }
            assertTrue(f.fence.exists())
            reopened.acknowledgeRepair(inspection) { true }
            assertFalse(reopened.read().repairPending)
            assertEquals(inspection.preference, reopened.read().preference)
        }
    }

    @Test fun unknownConcurrentCiphertextAndStaleRepairInspectionRemainPreserved(): Unit = Fixture().use { f ->
        val initial = f.store(); val before = initial.compareAndSet(initial.read(), preference()) { true }
        val other = Fixture()
        try {
            other.key = f.key
            val foreignStore = other.store()
            foreignStore.compareAndSet(foreignStore.read(), preference(true, 'c')) { true }
            val concurrent = other.state.readBytes()
            val changing = f.store { if (it == "before-publication") f.state.writeBytes(concurrent) }
            assertThrows(PhotoFolderScopeError::class.java) { changing.compareAndSet(before, preference(true, 'b')) { true } }
            assertArrayEquals(concurrent, f.state.readBytes()); assertTrue(f.store().read().repairPending)
            assertThrows(PhotoFolderScopeError::class.java) { f.store().inspectRepair() }
            assertArrayEquals(concurrent, f.state.readBytes()); assertTrue(f.fence.exists())
        } finally { other.close() }
    }

    @Test fun repairRechecksBothOriginalFenceAndStateWitnessesBeforeAcknowledgement(): Unit = Fixture().use { f ->
        val store = f.store()
        assertThrows(IOException::class.java) {
            f.store { if (it == "published") throw IOException("synthetic readback interruption") }
                .compareAndSet(store.read(), preference()) { true }
        }
        val reopened = f.store(); val inspection = reopened.inspectRepair()
        val original = f.fence.readBytes()
        f.fence.writeBytes(original.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
        val changed = f.fence.readBytes()
        assertThrows(Exception::class.java) { reopened.acknowledgeRepair(inspection) { true } }
        assertArrayEquals(changed, f.fence.readBytes())
        assertThrows(Exception::class.java) { reopened.read() }
    }

    @Test fun permissionLossAtPublicationOrFenceClearNeverEnablesAnUnfencedSource() {
        for (point in listOf("before-publication", "before-fence-clear")) Fixture().use { f ->
            var allowed = true
            val store = f.store { if (it == point) allowed = false }
            val absent = store.read()
            assertThrows(PhotoFolderScopeError::class.java) { store.compareAndSet(absent, preference(true)) { allowed } }
            assertTrue(f.store().read().repairPending)
            assertEquals(point == "before-fence-clear", f.store().inspectRepair().matchesWanted)
        }
    }

    @Test fun directorySyncFailureAfterFenceUnlinkReestablishesTheSameRepairFence(): Unit = Fixture().use { f ->
        var calls = 0
        val store = ProtectedPhotoFolderPreferences(f.root, f.protection, syncDirectory = {
            calls++
            if (calls == 3) throw IOException("synthetic unlink durability failure")
            io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner(it)
        })
        assertThrows(IOException::class.java) { store.compareAndSet(store.read(), preference()) { true } }
        assertTrue(f.fence.exists()); assertTrue(f.store().read().repairPending)
        assertTrue(f.store().inspectRepair().matchesWanted)
    }

    @Test fun linkedOrReplacedDirectoriesAndForeignStateLinksCannotBeAdopted(): Unit = Fixture().use { f ->
        val store = f.store(); store.compareAndSet(store.read(), preference()) { true }
        val original = f.state.readBytes()
        val foreign = File(f.root, "foreign-fixture").also { it.writeBytes(original) }
        f.state.delete(); Files.createSymbolicLink(f.state.toPath(), foreign.toPath())
        assertThrows(PhotoFolderScopeError::class.java) { store.read() }
        assertArrayEquals(original, foreign.readBytes())
        val held = File(f.root.parentFile, f.root.name + "-held")
        assertTrue(f.root.renameTo(held)); f.root.mkdir()
        try { assertThrows(PhotoFolderScopeError::class.java) { store.read() } }
        finally { f.root.delete(); assertTrue(held.renameTo(f.root)) }
        Unit
    }

    @Test fun actualNativeFileGateSerializesCompetingWritersWithoutLosingTheWinner(): Unit = Fixture().use { f ->
        val first = f.store(); val second = f.store(); val expected = first.read()
        val pool = java.util.concurrent.Executors.newFixedThreadPool(2)
        val start = java.util.concurrent.CountDownLatch(1)
        try {
            val tasks = listOf(first to 'a', second to 'b').map { (store, epoch) -> pool.submit<Boolean> {
                start.await()
                try { store.compareAndSet(expected, preference(epoch = epoch)) { true }; true }
                catch (_: PhotoFolderScopeError) { false }
            } }
            start.countDown()
            assertEquals(1, tasks.count { it.get(10, java.util.concurrent.TimeUnit.SECONDS) })
            assertTrue(f.store().read().preference!!.epoch in listOf("a".repeat(64), "b".repeat(64)))
            assertFalse(f.fence.exists())
        } finally { pool.shutdownNow(); assertTrue(pool.awaitTermination(10, java.util.concurrent.TimeUnit.SECONDS)) }
    }

    @Test fun hardLinkedStateAndNonRegularLockNeverAcquireStorageAuthority(): Unit = Fixture().use { f ->
        val store = f.store(); store.compareAndSet(store.read(), preference()) { true }
        val original = f.state.readBytes()
        val linked = File(f.root, "retained-fixture-link")
        Files.createLink(linked.toPath(), f.state.toPath())
        assertThrows(PhotoFolderScopeError::class.java) { store.read() }
        assertArrayEquals(original, linked.readBytes())
        linked.delete()
        val lock = File(f.root, "photo-source.lock")
        lock.delete(); lock.mkdir()
        assertThrows(PhotoFolderScopeError::class.java) { store.read() }
        assertArrayEquals(original, f.state.readBytes())
    }

    @Test fun authenticatedButMalformedMetadataStillUsesStrictFramingAndFieldTypes(): Unit = Fixture().use { f ->
        fun framed(bytes: ByteArray) = java.nio.ByteBuffer.allocate(bytes.size + 4).putInt(bytes.size).put(bytes).array()
        for (plain in listOf(framed("{\"format\":1,\"format\":1}".toByteArray()),
            framed(byteArrayOf('{'.code.toByte(), 0xff.toByte(), '}'.code.toByte())),
            framed("[]".toByteArray()), framed("{\"format\":true}".toByteArray()),
            framed("{\"format\":1}".toByteArray()) + byteArrayOf(0))) {
            val cipher = f.protection.seal(plain, "photo-source-preferences-v1/photo-source.enc")
            Files.write(f.state.toPath(), cipher)
            Files.setPosixFilePermissions(f.state.toPath(), PosixFilePermissions.fromString("rw-------"))
            assertThrows(Exception::class.java) { f.store().read() }
            assertArrayEquals(cipher, f.state.readBytes())
        }
    }

    @Test fun realStoreFenceBlocksRecreatedNativeScopeUntilExplicitRepair(): Unit = Fixture().use { f ->
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64),
            true, true, true, true, true, true, 1)
        val trees = object : ReadOnlyPhotoTrees {
            override fun canonicalTree(uri: String) = uri.also { require(it == preference().treeUri) }
            override fun persistRead(uri: String) { canonicalTree(uri) }
            override fun readGrantToken(uri: String) = "d".repeat(64)
        }
        var fail = false
        val store = f.store { if (fail && it == "published") throw IOException("synthetic uncertain applied preference") }
        val scope = PhotoFolderScope({ receiver }, trees, store)
        scope.completePicker(scope.beginPicker(), preference().treeUri)
        assertNull(scope.lease())
        fail = true
        assertThrows(IOException::class.java) { scope.setEnabled(true) }
        assertNull(scope.lease())
        val reopened = f.store()
        val newScope = PhotoFolderScope({ receiver }, trees, reopened)
        assertNull(newScope.lease())
        val inspection = reopened.inspectRepair()
        assertTrue(inspection.matchesWanted)
        reopened.acknowledgeRepair(inspection) { receiver.allowed }
        assertNotNull(PhotoFolderScope({ receiver }, trees, reopened).lease())
        assertNull(scope.lease()) // The original uncertain controller is not silently repaired.
    }
}
