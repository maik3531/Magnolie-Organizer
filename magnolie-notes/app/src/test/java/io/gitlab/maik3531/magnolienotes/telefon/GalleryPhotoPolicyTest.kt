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
    @Test fun existingOnlyProjectionNeverCreatesAMissingIndex() {
        Fixture().use { fixture ->
            assertThrows(PhotoFolderScopeError::class.java) { PhotoSourceJobIndex.openExisting(fixture.root, fixture.protection) }
            assertFalse(File(fixture.root, "photo-source-jobs.db").exists())
            fixture.open().use { assertNull(it.galleryPolicy().policy) }
            PhotoSourceJobIndex.openExisting(fixture.root, fixture.protection).use { assertNull(it.galleryPolicy().policy) }
        }
    }
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
        fun rows() = SQLiteDatabase.openDatabase(File(root, "photo-source-jobs.db").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            val result = mutableMapOf<String, List<Byte>>()
            db.rawQuery("SELECT name,sealed FROM source_meta ORDER BY name", null).use {
                while (it.moveToNext()) result[it.getString(0)] = it.getBlob(1).toList()
            }
            result
        }
        override fun close() { root.deleteRecursively() }
    }

    @Test fun actualFileControlConfigurerBootstrapsProtectedWorkflowWithoutPretendingToHaveDataOrOsRead() {
        Fixture().use { f -> f.open().use { index ->
            val localIdentity = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
            val pcIdentity = NativeFileControlIdentity("receiver_fixture_01", "e".repeat(64))
            val localOwner = Any(); val pcOwner = Any()
            val localPeer = NativeFileControlPeer(pcIdentity.deviceId, pcIdentity.identitySha256, Any(), true, true, true, true, true)
            val pcPeer = NativeFileControlPeer(localIdentity.deviceId, localIdentity.identitySha256, Any(), true, true, true, true, true)
            var confirmed = DeviceFileGrantState(1, "0".repeat(64), false, false)
            fun localState(): NativeLocalFileGrant {
                val snapshot = index.galleryPolicy()
                if (snapshot.repairPending) return NativeLocalFileGrant(confirmed, localOwner, true, policyReady = false)
                snapshot.policy?.let { confirmed = DeviceFileGrantState(it.revision, it.epoch, it.enabled, false) }
                return NativeLocalFileGrant(confirmed, localOwner, true)
            }
            val source = NativeFileControlSession(localIdentity, { localPeer }, ::localState)
            val desktop = NativeFileControlSession(pcIdentity, { pcPeer }, {
                NativeLocalFileGrant(DeviceFileGrantState(7, "b".repeat(64), false, true), pcOwner, true)
            })
            fun send(first: NativeFileControlSession, second: NativeFileControlSession, peer: NativeFileControlPeer) {
                val packet = first.packet(); first.markSent(packet)
                second.observeRemote(DeviceFileControlPacket.parse(packet.wire()), peer)
            }
            send(source, desktop, pcPeer); send(desktop, source, localPeer); send(source, desktop, pcPeer)
            assertNull(source.photoReceiver())
            val ticket = source.configurationTicket()
            val app = org.robolectric.RuntimeEnvironment.getApplication()
            NativeGalleryPhotoWorkflow.forAuthenticatedConfigurer(app, f.root, localIdentity.deviceId, f.protection,
                { source.photoReceiver() }, { source.configurationAuthority(ticket) }).use { workflow ->
                val saved = workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                assertEquals(2L, saved.policy!!.revision)
                assertEquals(JsonPrimitive(2), saved.policy!!.wire()["format"])
                assertNotNull(source.configurationAuthority(ticket)) // Its own policy publication did not revoke the command.
                assertNull(workflow.currentRequest()) // New data consent still needs fresh native echo.
                source.finishConfiguration(ticket)
                send(source, desktop, pcPeer); send(desktop, source, localPeer)
                assertTrue(workflow.currentRequest()!!.receiver.allowed)
                org.robolectric.Shadows.shadowOf(app).denyPermissions(android.Manifest.permission.READ_EXTERNAL_STORAGE)
                assertEquals(GalleryReadCoverage.NONE, AndroidGalleryReadPermissions.observe(app))
                val catalog = AndroidGalleryAlbumDiscovery(app, { workflow.currentRequest() }).discover()
                assertEquals(GalleryReadCoverage.NONE, catalog.coverage)
                assertTrue(catalog.albums.isEmpty()) // Dedicated grants cannot manufacture Android READ.
            }
            source.close(); desktop.close()
        } }
    }

    @Test fun legacyPolicyBytesRemainReadableAndUnchangedWhileRealPolicyChangesGetMonotonicRevision2() {
        Fixture().use { f -> f.open().use { index ->
            val legacy = f.policy()
            val restored = GalleryPhotoPolicy.parse(legacy.wire())
            assertEquals(1L, restored.revision); assertEquals(legacy.wire(), restored.wire())
            val stored = index.compareAndSetGalleryPolicy(index.galleryPolicy(), legacy) { true }
            val controller = GalleryPhotoPolicyController(index) { f.receiver }
            assertEquals(stored, controller.configure(stored, true, legacy.kinds))
            assertEquals(stored, index.galleryPolicy()) // No nonce/revision/epoch churn on unchanged settings.
            val changed = controller.configure(stored, true, setOf(GallerySourceKind.SCREENSHOTS))
            assertEquals(2L, changed.policy!!.revision)
            assertEquals(JsonPrimitive(2), changed.policy!!.wire()["format"])
            assertEquals(changed.policy!!.wire(), GalleryPhotoPolicy.parse(changed.policy!!.wire()).wire())
            assertNotEquals(legacy.epoch, changed.policy!!.epoch)
            assertEquals(changed, controller.configure(changed, true, changed.policy!!.kinds))
        } }
    }

    @Test fun authenticatedConfigurerCannotFallBackToAnUnrelatedAllowedDataReceiverOrDowngradeItsCounter() {
        Fixture().use { f -> f.open().use { index ->
            val controlled = GalleryPhotoPolicyController.forAuthenticatedConfigurer(index, { f.receiver }, { null })
            assertEquals("gallery_configurer_not_ready", assertThrows(PhotoFolderScopeError::class.java) {
                controlled.configure(index.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA)) }.code)
            val empty = index.galleryPolicy()
            assertNull(empty.policy); assertEquals(empty, controlled.disableLocally(empty))
            val controller = GalleryPhotoPolicyController(index) { f.receiver }
            val saved = controller.configure(empty, true, setOf(GallerySourceKind.CAMERA))
            assertEquals(2L, saved.policy!!.revision)
            assertEquals("gallery_policy_revision_conflict", assertThrows(PhotoFolderScopeError::class.java) {
                index.compareAndSetGalleryPolicy(saved, f.policy("c".repeat(64))) { true } }.code)
            assertEquals(saved, index.galleryPolicy())
            f.receiver = null
            val disabled = controlled.disableLocally(saved)
            assertFalse(disabled.policy!!.enabled); assertEquals(3L, disabled.policy!!.revision)
        } }
    }

    @Test fun strictPolicyRevisionParsingRejectsBooleanAliasesMissingCountersAndRollback() {
        val valid = GalleryPhotoPolicy("receiver_fixture_01", "e".repeat(64), "a".repeat(64), true,
            setOf(GallerySourceKind.CAMERA), 2, 2).wire()
        for (value in listOf(JsonObject(valid - "revision"), JsonObject(valid + ("revision" to JsonPrimitive(true))),
            JsonObject(valid + ("revision" to JsonPrimitive("2"))), JsonObject(valid + ("revision" to JsonPrimitive(0))),
            JsonObject(valid + ("revision" to JsonPrimitive(DeviceFileControl.MAX_REVISION + 1)))))
            assertThrows(PhotoFolderScopeError::class.java) { GalleryPhotoPolicy.parse(value) }
    }

    @Test fun remoteDisableRequiresItsExactConfigurerThroughoutPolicyCasWhileLocalRevocationStaysAvailable() {
        for (boundary in listOf("gallery-policy-fenced", "gallery-policy-published")) {
            Fixture().use { f ->
                var configured: NativeGalleryConfigurer? = NativeGalleryConfigurer("receiver_fixture_01", "e".repeat(64),
                    Any(), "b".repeat(64), true, true, true, true)
                var revokeAt: String? = null
                f.open { if (it == revokeAt) configured = null }.use { index ->
                    val controller = GalleryPhotoPolicyController.forAuthenticatedConfigurer(index, { f.receiver }, { configured })
                    val enabled = controller.configure(index.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA))
                    revokeAt = boundary
                    assertThrows(PhotoFolderScopeError::class.java) { controller.configure(enabled, false, emptySet()) }
                    assertTrue(index.galleryPolicy().repairPending)
                    assertNull(controller.currentRequest())
                    revokeAt = null
                    index.acknowledgeGalleryPolicyRepair(index.inspectGalleryPolicyRepair()) { true }
                    val saved = index.galleryPolicy()
                    val local = GalleryPhotoPolicyController.forAuthenticatedConfigurer(index, { null }, { null })
                    val disabled = local.disableLocally(saved)
                    assertFalse(disabled.policy!!.enabled)
                    assertFalse(disabled.repairPending)
                }
            }
        }
    }

    @Test fun protectedGrantFactoryRequiresExplicitCurrentPairingAssociationAndDoesNotRewriteLegacyPolicy() {
        Fixture().use { f -> f.open().use { index ->
            val peer = NativeFileControlPeer("receiver_fixture_01", "e".repeat(64), Any(), true, true, true, true, true, "1".repeat(64))
            val factory = NativeGalleryFileGrantPolicy({ peer }, { index.galleryPolicy() }, { true })
            assertFalse(factory.current()!!.grants.sendFiles)
            assertNull(index.galleryPolicy().policy) // No saved off default from reading.
            val legacy = index.compareAndSetGalleryPolicy(index.galleryPolicy(), f.policy()) { true }
            val native = NativeGalleryFileGrantPolicy({ peer }, { index.galleryPolicy() }, { true })
            assertFalse(native.current()!!.grants.sendFiles)
            assertEquals(legacy, index.galleryPolicy())
            val configured = NativeGalleryConfigurer(peer.peerId, peer.identitySha256, Any(), "b".repeat(64), true, true, true, true, peer.pairingEpoch)
            val controller = GalleryPhotoPolicyController.forAuthenticatedConfigurer(index, { f.receiver }, { configured })
            val associated = controller.configure(legacy, true, legacy.policy!!.kinds)
            assertEquals(JsonPrimitive(3), associated.policy!!.wire()["format"])
            assertEquals(peer.pairingEpoch, associated.policy!!.pairingEpoch)
            assertEquals(2L, associated.policy!!.revision)
            assertTrue(native.current()!!.grants.sendFiles)
            assertFalse(native.current()!!.grants.receiveFiles)
            assertEquals(associated, controller.configure(associated, true, associated.policy!!.kinds))
            assertEquals(associated.policy!!.epoch, native.current()!!.grants.epoch)
            assertEquals(associated.policy!!.wire(), GalleryPhotoPolicy.parse(associated.policy!!.wire()).wire())
            assertNull(controller.currentRequest()) // Old unassociated source receiver is not adopted.
            f.receiver = f.receiver!!.copy(pairingEpoch = peer.pairingEpoch)
            assertNotNull(controller.currentRequest())
        } }
    }

    @Test fun pairingAssociatedGrantFactoryFencesPolicyCasAndNeverReactivatesOnRePairWithSameIdAndKey() {
        Fixture().use { f ->
            var peer = NativeFileControlPeer("receiver_fixture_01", "e".repeat(64), Any(), true, true, true, true, true, "1".repeat(64))
            lateinit var factory: NativeGalleryFileGrantPolicy
            var observeFence = false
            var sawFence = false
            f.open { if (observeFence && it == "gallery-policy-fenced") {
                val blocked = factory.current()!!
                assertFalse(blocked.policyReady); assertTrue(blocked.grants.sendFiles)
                sawFence = true
            } }.use { index ->
                fun configurer() = NativeGalleryConfigurer(peer.peerId, peer.identitySha256, Any(), "b".repeat(64), true, true, true, true, peer.pairingEpoch)
                var authority = configurer()
                val controller = GalleryPhotoPolicyController.forAuthenticatedConfigurer(index, { null }, { authority })
                val first = controller.configure(index.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA))
                factory = NativeGalleryFileGrantPolicy({ peer }, { index.galleryPolicy() }, { true })
                val confirmed = factory.current()!!
                assertTrue(confirmed.grants.sendFiles)
                observeFence = true
                val second = controller.configure(first, true, setOf(GallerySourceKind.SCREENSHOTS))
                assertTrue(sawFence); assertTrue(factory.current()!!.policyReady)
                assertNotEquals(confirmed.grants.epoch, factory.current()!!.grants.epoch)
                observeFence = false
                peer = peer.copy(pairingEpoch = "2".repeat(64))
                assertNull(factory.current()) // Old owner cannot adopt a new relationship.
                val replacement = NativeGalleryFileGrantPolicy({ peer }, { index.galleryPolicy() }, { true })
                assertFalse(replacement.current()!!.grants.sendFiles)
                assertEquals(second, index.galleryPolicy())
                authority = configurer()
                val reauthorized = controller.configure(second, true, second.policy!!.kinds)
                assertEquals(4L, reauthorized.policy!!.revision)
                assertTrue(replacement.current()!!.grants.sendFiles)
                assertNotEquals(second.policy!!.epoch, replacement.current()!!.grants.epoch)
                val downgrade = GalleryPhotoPolicy(peer.peerId, peer.identitySha256, "c".repeat(64), false,
                    emptySet(), reauthorized.policy!!.revision + 1, 2)
                assertEquals("gallery_policy_pairing_downgrade", assertThrows(PhotoFolderScopeError::class.java) {
                    index.compareAndSetGalleryPolicy(reauthorized, downgrade) { true } }.code)
            }
        }
    }

    @Test fun nativeGrantFactoryNeverInventsPairingEpochOrRecoversFromAnUncertainProtectedRead() {
        Fixture().use { f -> f.open().use { index ->
            var peer = NativeFileControlPeer("receiver_fixture_01", "e".repeat(64), Any(), true, true, true, true, true)
            var reads = 0
            val factory = NativeGalleryFileGrantPolicy({ peer }, { reads++; index.galleryPolicy() }, { true })
            assertNull(factory.current()); assertEquals(0, reads)
            peer = peer.copy(pairingEpoch = "1".repeat(64))
            assertFalse(factory.current()!!.grants.sendFiles)
            var fail = true
            val uncertain = NativeGalleryFileGrantPolicy({ peer }, { if (fail) throw IOException("protected read failed") else index.galleryPolicy() }, { true })
            assertThrows(IOException::class.java) { uncertain.current() }
            fail = false
            assertNull(uncertain.current())
            assertNull(index.galleryPolicy().policy)
        } }
    }

    @Test fun restartedGrantFactoryDoesNotInventConfirmedGrantFromPendingPolicyRevision() {
        Fixture().use { f ->
            var fault = true
            val peer = NativeFileControlPeer("receiver_fixture_01", "e".repeat(64), Any(), true, true, true, true, true, "1".repeat(64))
            val authority = NativeGalleryConfigurer(peer.peerId, peer.identitySha256, Any(), "b".repeat(64), true, true, true, true, peer.pairingEpoch)
            f.open { if (fault && it == "gallery-policy-published") throw IOException("interrupted associated policy") }.use { index ->
                val controller = GalleryPhotoPolicyController.forAuthenticatedConfigurer(index, { null }, { authority })
                assertThrows(IOException::class.java) { controller.configure(index.galleryPolicy(), true, setOf(GallerySourceKind.CAMERA)) }
                fault = false
                val restarted = NativeGalleryFileGrantPolicy({ peer }, { index.galleryPolicy() }, { true })
                assertNull(restarted.current())
                val pending = index.galleryPolicy()
                assertTrue(pending.repairPending)
                index.acknowledgeGalleryPolicyRepair(index.inspectGalleryPolicyRepair()) { true }
                val confirmed = restarted.current()!!
                assertTrue(confirmed.policyReady); assertTrue(confirmed.grants.sendFiles)
                assertEquals(pending.policy!!.revision, confirmed.grants.revision)
                assertEquals(pending.policy!!.epoch, confirmed.grants.epoch)
            }
        }
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

    @Test fun missingProtectedPolicyCannotBecomeDisabledDefaultUnderOriginalMembership() {
        Fixture().use { f ->
            f.open().use { it.compareAndSetGalleryPolicy(it.galleryPolicy(), f.policy()) { true } }
            val original = f.rows()
            SQLiteDatabase.openDatabase(File(f.root, "photo-source-jobs.db").path, null, SQLiteDatabase.OPEN_READWRITE).use {
                assertEquals(1, it.delete("source_meta", "name=?", arrayOf("gallery-policy-v1")))
            }
            val remaining = f.rows()
            assertEquals(original - "gallery-policy-v1", remaining)
            assertEquals("photo_jobs_membership_changed", assertThrows(PhotoFolderScopeError::class.java) { f.open().close() }.code)
            assertEquals(remaining, f.rows())
        }
    }

    @Test fun missingKeyCorruptStateAndCorruptFenceNeverBecomeDefaultPolicies() {
        Fixture().use { f ->
            f.open().use { it.compareAndSetGalleryPolicy(it.galleryPolicy(), f.policy()) { true } }
            val original = f.key; f.key = null
            assertThrows(DeviceTransferKeyUnavailable::class.java) { f.open().close() }; assertNull(f.key)
            f.key = original
            f.replaceRow("gallery-policy-v1", byteArrayOf(1, 2, 3))
            val rows = f.rows()
            assertThrows(PhotoFolderScopeError::class.java) { f.open().use { it.galleryPolicy() } }
            assertEquals(rows, f.rows())
        }
        Fixture().use { f ->
            f.open { if (it == "gallery-policy-fenced") throw IOException("synthetic interrupted operation") }.use { index ->
                assertThrows(IOException::class.java) { index.compareAndSetGalleryPolicy(index.galleryPolicy(), f.policy()) { true } }
            }
            f.replaceRow("gallery-policy-v1-repair", byteArrayOf(1, 2, 3))
            val rows = f.rows()
            assertThrows(PhotoFolderScopeError::class.java) { f.open().use { it.galleryPolicy() } }
            assertEquals(rows, f.rows())
        }
    }

    @Test fun unknownConcurrentAuthenticatedPolicyAndChangedRepairHeadsArePreserved() {
        Fixture().use { f ->
            f.open { if (it == "gallery-policy-published") throw IOException("synthetic publication acknowledgement loss") }.use { index ->
                assertThrows(IOException::class.java) { index.compareAndSetGalleryPolicy(index.galleryPolicy(), f.policy()) { true } }
            }
            assertTrue(f.open().use { it.inspectGalleryPolicyRepair().state.repairPending })
            val unknown = f.policy("b".repeat(64))
            f.replaceRow("gallery-policy-v1", f.seal(unknown.wire(), "gallery-policy-v1"))
            // A valid independently sealed row is not an authenticated aggregate
            // update. Reject before policy/repair exposure and preserve it all.
            val rows = f.rows()
            assertEquals("photo_jobs_membership_changed", assertThrows(PhotoFolderScopeError::class.java) { f.open().close() }.code)
            assertEquals(rows, f.rows())
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
            val rows = f.rows()
            assertEquals("photo_jobs_membership_unknown_metadata", assertThrows(PhotoFolderScopeError::class.java) { f.open().close() }.code)
            assertEquals(rows, f.rows())
            SQLiteDatabase.openDatabase(File(f.root, "photo-source-jobs.db").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT sealed FROM source_meta WHERE name='unrelated-fixture'", null).use {
                    assertTrue(it.moveToFirst()); assertArrayEquals(byteArrayOf(4, 2), it.getBlob(0))
                }
            }
        }
    }
}
