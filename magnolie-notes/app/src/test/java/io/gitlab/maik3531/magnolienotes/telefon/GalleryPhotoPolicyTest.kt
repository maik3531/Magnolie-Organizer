package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.database.sqlite.SQLiteDatabase
import android.os.CancellationSignal
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.ByteArrayOutputStream
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class GalleryPhotoPolicyTest {
    private class Fixture : AutoCloseable {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "gallery-policy329-").toFile()
        var key: SecretKey? = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        val protection = DeviceTransferProtection.fromExistingKeyReader { key }
        var receiver: NativePhotoReceiver? = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        fun open(hook: (String) -> Unit = {}) = PhotoSourceJobIndex(root, protection, hook)
        fun policy(epoch: String = "a".repeat(64)) = GalleryPhotoPolicy("receiver_fixture_01", "e".repeat(64), epoch, true, setOf(GallerySourceKind.CAMERA))
        fun replaceRow(name: String, bytes: ByteArray) = SQLiteDatabase.openDatabase(File(root, "photo-source-jobs.db").path, null, SQLiteDatabase.OPEN_READWRITE).use {
            it.execSQL("UPDATE source_meta SET sealed=? WHERE name=?", arrayOf(bytes, name))
        }
        fun seal(value: JsonObject, name: String) = protection.seal(ByteArrayOutputStream().also {
            TelefonRahmen.schreiben(it, value, DeviceTransferProtection.MAX_CLEAR_BYTES - 4)
        }.toByteArray(), "photo-source-jobs-v1/$name")
        override fun close() { root.deleteRecursively() }
    }

    @Test fun actualPolicyBackedGalleryAuthorityCanFreezePublishOfferAndRetireUnderTheSameNativeIndexGate() {
        Fixture().use { f -> f.open().use { index ->
            val controller = GalleryPhotoPolicyController(index) { f.receiver }
            val saved = controller.configure(index.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA))
            val environment = object : GalleryAccessEnvironment {
                override fun observe(volume: String) = GalleryAccessObservation(GalleryReadCoverage.FULL_IMAGES, "d".repeat(64), "fixture-store-v1", true)
            }
            val scope = GalleryPhotoSourceScope({ controller.currentRequest() }, environment)
            val album = GalleryAlbumCandidate(GallerySourceKind.CAMERA, "external", "camera", "Camera", null, 1, false)
            val lease = scope.capture(GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(album), controller.currentRequest()), album)
            val inventory = PhotoSourceInventory(lease, listOf(PhotoInventoryEntry("content://media/external/images/media/1", "1:90", "image.jpg", 5, 100000)))
            val source = object : PhotoSourceAccess {
                override fun verifyMetadata(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal) { check(scope.isCurrent(lease)) }
                override fun openRead(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal) = ByteArrayInputStream("hello".toByteArray())
            }
            val reserved = index.reserve(inventory, scope)
            val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, "sender_fixture_01", scope, source, f.protection)
            val sealed = index.publishSnapshot(reserved, snapshot, scope, lease)
            val reader = index.restore(sealed, "sender_fixture_01", scope, lease)
            assertEquals("file_transfer.offer", (reader.offerMessage()["kind"] as JsonPrimitive).content)
            assertArrayEquals("hello".toByteArray(), reader.readChunk(reader.manifest.files.single().id, 0))
            controller.configure(saved, false, emptySet())
            assertThrows(PhotoFolderScopeError::class.java) { reader.offerMessage() }
            index.retireCachedSnapshot(index.jobs().single())
            assertTrue(index.jobs().isEmpty())
        } }
    }

    @Test fun nestedNativePolicyReadsAcrossTwoIndexObjectsReuseOnlyTheSameThreadHeldRootLock() {
        Fixture().use { f -> f.open().use { writer -> f.open().use { policyReader ->
            val controller = GalleryPhotoPolicyController(policyReader) { f.receiver }
            controller.configure(policyReader.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA))
            val request = controller.currentRequest()!!
            val lease = object : NativePhotoSourceLease {
                override val sourceKey = "native-fixture-source"
                override val sourceEpoch = request.policyEpoch
                override val version = "c".repeat(64)
                override val receiver = request.receiver
                override val readGrantToken = "d".repeat(64)
            }
            val authority = object : NativePhotoSourceAuthority {
                override fun isCurrent(lease: NativePhotoSourceLease) = controller.currentRequest()?.policyEpoch == request.policyEpoch
            }
            val inventory = PhotoSourceInventory(lease, listOf(PhotoInventoryEntry("fixture", "1", "photo.jpg", 5, 100)))
            val job = writer.reserve(inventory, authority)
            assertEquals("reserved", job.phase)
            writer.retireAndClean(job) { assertTrue(writer.rootFile(job).delete()) }
            // A callback failure must unwind the reused-lock bookkeeping too.
            val broken = object : NativePhotoSourceAuthority {
                override fun isCurrent(lease: NativePhotoSourceLease): Boolean { policyReader.galleryPolicy(); throw IOException("synthetic callback failure") }
            }
            assertThrows(IOException::class.java) { writer.reserve(inventory, broken) }
            assertTrue(writer.jobs().isEmpty()); assertNotNull(policyReader.galleryPolicy().policy)
            val fresh = writer.reserve(inventory, authority)
            writer.retireAndClean(fresh) { assertTrue(writer.rootFile(fresh).delete()) }
        } } }
    }

    @Test fun actualProtectedPolicyPersistsSeparatelyWithAbsenceOffAndFrozenKinds() {
        Fixture().use { f ->
            val saved: GalleryPhotoPolicySnapshot
            f.open().use { index ->
                val initial = index.galleryPolicy()
                assertNull(initial.policy); assertFalse(initial.repairPending)
                val kinds = mutableSetOf(GallerySourceKind.WHATSAPP_RECEIVED)
                val policy = GalleryPhotoPolicy("receiver_fixture_01", "e".repeat(64), "a".repeat(64), true, kinds)
                kinds.add(GallerySourceKind.CAMERA)
                saved = index.compareAndSetGalleryPolicy(initial, policy) { true }
                assertEquals(setOf(GallerySourceKind.WHATSAPP_RECEIVED), saved.policy!!.kinds)
                assertThrows(UnsupportedOperationException::class.java) { (saved.policy.kinds as MutableSet<GallerySourceKind>).clear() }
                assertTrue(index.jobs().isEmpty())
            }
            f.open().use { assertEquals(saved, it.galleryPolicy()) }
            val raw = File(f.root, "photo-source-jobs.db").readBytes().toString(Charsets.ISO_8859_1)
            assertFalse(raw.contains("receiver_fixture_01")); assertFalse(raw.contains("WHATSAPP_RECEIVED"))
        }
    }

    @Test fun twoNativeStoresCannotLoseASimultaneousPolicyEdit() {
        Fixture().use { f -> f.open().use { first -> f.open().use { second ->
            val expected = first.galleryPolicy(); val start = CountDownLatch(1)
            val pool = Executors.newFixedThreadPool(2)
            try {
                val results = listOf(first, second).mapIndexed { number, index -> pool.submit<Boolean> {
                    check(start.await(5, TimeUnit.SECONDS))
                    try { index.compareAndSetGalleryPolicy(expected, f.policy(if (number == 0) "a".repeat(64) else "b".repeat(64))) { true }; true }
                    catch (error: PhotoFolderScopeError) { assertEquals("gallery_policy_cas_conflict", error.code); false }
                } }
                start.countDown()
                assertEquals(1, results.count { it.get(10, TimeUnit.SECONDS) })
                assertEquals(first.galleryPolicy(), second.galleryPolicy()); assertFalse(first.galleryPolicy().repairPending)
            } finally { pool.shutdownNow(); assertTrue(pool.awaitTermination(5, TimeUnit.SECONDS)) }
        } } }
    }

    @Test fun lostFencePublicationOrClearAcknowledgementsStayDurablyFencedUntilExplicitExactRepair() {
        for (point in listOf("gallery-policy-fenced", "gallery-policy-published", "gallery-policy-fence-cleared")) Fixture().use { f ->
            f.open { if (it == point) throw IOException("synthetic policy acknowledgement loss") }.use { index ->
                assertThrows(IOException::class.java) { index.compareAndSetGalleryPolicy(index.galleryPolicy(), f.policy()) { true } }
            }
            f.open().use { index ->
                val held = index.galleryPolicy(); assertTrue(held.repairPending)
                assertEquals(point != "gallery-policy-fenced", held.policy != null)
                val inspection = index.inspectGalleryPolicyRepair()
                assertEquals(point != "gallery-policy-fenced", inspection.matchesWanted)
                assertThrows(PhotoFolderScopeError::class.java) { index.compareAndSetGalleryPolicy(held, f.policy("b".repeat(64))) { true } }
                index.acknowledgeGalleryPolicyRepair(inspection) { true }
                assertFalse(index.galleryPolicy().repairPending)
                assertEquals(held.policy, index.galleryPolicy().policy) // No rollback/roll-forward.
                assertEquals(held.version, index.galleryPolicy().version)
            }
        }
    }

    @Test fun permissionLossAtActualPublicationAndAfterFenceClearCannotActivateOrResetPolicy() {
        for (point in listOf("gallery-policy-fenced", "gallery-policy-published", "gallery-policy-fence-cleared")) Fixture().use { f ->
            var allowed = true
            f.open { if (it == point) allowed = false }.use { index ->
                assertThrows(PhotoFolderScopeError::class.java) { index.compareAndSetGalleryPolicy(index.galleryPolicy(), f.policy()) { allowed } }
                val held = index.galleryPolicy(); assertTrue(held.repairPending)
                val inspection = index.inspectGalleryPolicyRepair()
                assertThrows(PhotoFolderScopeError::class.java) { index.acknowledgeGalleryPolicyRepair(inspection) { false } }
                assertEquals(held, index.galleryPolicy())
            }
        }
    }

    @Test fun missingKeyCorruptStateAndCorruptFenceNeverBecomeDefaultPolicies() {
        Fixture().use { f ->
            f.open().use { it.compareAndSetGalleryPolicy(it.galleryPolicy(), f.policy()) { true } }
            val original = f.key; f.key = null
            assertThrows(DeviceTransferKeyUnavailable::class.java) { f.open().close() }; assertNull(f.key)
            f.key = original
            f.replaceRow("gallery-policy-v1", byteArrayOf(1, 2, 3))
            f.open().use { assertThrows(PhotoFolderScopeError::class.java) { it.galleryPolicy() } }
        }
        Fixture().use { f ->
            f.open { if (it == "gallery-policy-fenced") throw IOException("synthetic interrupted operation") }.use { index ->
                assertThrows(IOException::class.java) { index.compareAndSetGalleryPolicy(index.galleryPolicy(), f.policy()) { true } }
            }
            f.replaceRow("gallery-policy-v1-repair", byteArrayOf(1, 2, 3))
            f.open().use { assertThrows(PhotoFolderScopeError::class.java) { it.galleryPolicy() } }
        }
    }

    @Test fun unknownConcurrentAuthenticatedPolicyAndChangedRepairHeadsArePreserved() {
        Fixture().use { f ->
            f.open { if (it == "gallery-policy-published") throw IOException("synthetic publication acknowledgement loss") }.use { index ->
                assertThrows(IOException::class.java) { index.compareAndSetGalleryPolicy(index.galleryPolicy(), f.policy()) { true } }
            }
            val inspection = f.open().use { it.inspectGalleryPolicyRepair() }
            val unknown = f.policy("b".repeat(64))
            f.replaceRow("gallery-policy-v1", f.seal(unknown.wire(), "gallery-policy-v1"))
            f.open().use { index ->
                assertEquals(unknown, index.galleryPolicy().policy); assertTrue(index.galleryPolicy().repairPending)
                assertEquals("gallery_policy_unknown_concurrent_state", assertThrows(PhotoFolderScopeError::class.java) { index.inspectGalleryPolicyRepair() }.code)
                assertThrows(PhotoFolderScopeError::class.java) { index.acknowledgeGalleryPolicyRepair(inspection) { true } }
                assertEquals(unknown, index.galleryPolicy().policy)
            }
        }
    }

    @Test fun nativeControllerUsesLocalEpochsAndProtectedPolicyButNeverInfersAndroidReadPermission() {
        Fixture().use { f -> f.open().use { index ->
            val controller = GalleryPhotoPolicyController(index) { f.receiver }
            assertNull(controller.currentRequest())
            val saved = controller.configure(index.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA))
            val request = controller.currentRequest()!!
            assertSame(f.receiver, request.receiver); assertEquals(saved.policy!!.epoch, request.policyEpoch)
            assertTrue(Regex("[0-9a-f]{64}").matches(request.policyEpoch))
            f.receiver = f.receiver!!.copy(identitySha256 = "d".repeat(64))
            assertNull(controller.currentRequest())
            assertThrows(PhotoFolderScopeError::class.java) { controller.configure(saved, true, setOf(GallerySourceKind.SCREENSHOTS)) }
            f.receiver = null
            val disabled = controller.configure(saved, false, emptySet())
            assertFalse(disabled.policy!!.enabled); assertNull(controller.currentRequest())
            assertNotEquals(saved.policy.epoch, disabled.policy.epoch)
        } }
    }

    @Test fun repairedStoreDoesNotUnfenceAnUncertainNativeControllerOrOverwriteOtherRows() {
        Fixture().use { f ->
            var fault = true
            f.open { if (fault && it == "gallery-policy-published") throw IOException("synthetic uncertain policy commit") }.use { index ->
                val controller = GalleryPhotoPolicyController(index) { f.receiver }
                assertThrows(IOException::class.java) { controller.configure(index.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA)) }
                fault = false
                index.acknowledgeGalleryPolicyRepair(index.inspectGalleryPolicyRepair()) { true }
                assertNull(controller.currentRequest())
                assertNotNull(GalleryPhotoPolicyController(index) { f.receiver }.currentRequest())
            }
            SQLiteDatabase.openDatabase(File(f.root, "photo-source-jobs.db").path, null, SQLiteDatabase.OPEN_READWRITE).use {
                it.execSQL("INSERT INTO source_meta(name,sealed) VALUES(?,?)", arrayOf("unrelated-fixture", byteArrayOf(4, 2)))
            }
            f.open().use { index -> index.compareAndSetGalleryPolicy(index.galleryPolicy(), f.policy("c".repeat(64))) { true } }
            SQLiteDatabase.openDatabase(File(f.root, "photo-source-jobs.db").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT sealed FROM source_meta WHERE name='unrelated-fixture'", null).use {
                    assertTrue(it.moveToFirst()); assertArrayEquals(byteArrayOf(4, 2), it.getBlob(0))
                }
            }
        }
    }
}
