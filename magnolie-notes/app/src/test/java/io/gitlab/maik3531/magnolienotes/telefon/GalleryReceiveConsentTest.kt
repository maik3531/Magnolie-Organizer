package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.AlertDialog
import android.app.Application
import android.content.Context
import android.content.ContextWrapper
import android.content.DialogInterface
import android.content.pm.PackageManager
import android.database.sqlite.SQLiteDatabase
import android.os.Looper
import androidx.activity.ComponentActivity
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowAlertDialog
import java.io.File
import java.nio.file.Files
import java.util.concurrent.Callable
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class GalleryReceiveConsentTest {
    internal class Prompt(val dialog: AlertDialog, val result: AtomicReference<Result<NativeGalleryReceiveConsent>?>)
    internal class Fixture : AutoCloseable {
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "gallery-receive338-").toFile()
        val app = RuntimeEnvironment.getApplication()
        private val bookRoot = Files.createTempDirectory(root.toPath(), "book-").toFile()
        private val context = object : ContextWrapper(app) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = bookRoot
        }
        val documents = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 37 }, "AES") }.also { it.setzePapierkorb(false, 7) }
        var currentDocuments: Ablage? = documents
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 41 }, "AES") }
        val indexRoot = Files.createTempDirectory(root.toPath(), "policy-").toFile()
        var hook: (String) -> Unit = {}
        val index = PhotoSourceJobIndex(indexRoot, protection) { hook(it) }
        val pc = NativeFileControlIdentity("receiver_fixture_01", "e".repeat(64))
        private val phone = NativeFileControlIdentity("phone_fixture_0001", "a".repeat(64))
        var peer = NativeFileControlPeer(pc.deviceId, pc.identitySha256, Any(), true, true, true, true, true, "f".repeat(64))
        private var pcPeer = NativeFileControlPeer(phone.deviceId, phone.identitySha256, Any(), true, true, true, true, true, "f".repeat(64))
        private var pcLocal = NativeLocalFileGrant(DeviceFileGrantState(3, "d".repeat(64), true, true), Any(), true)
        var unlocked = true
        var handlerReady = true
        var sourceBusy = false
        var now = 100L
        var ticket: NativeFileConfigurationTicket? = null
        lateinit var session: NativeFileControlSession
        private lateinit var pcSession: NativeFileControlSession
        lateinit var controller: GalleryReceivePolicyController
        lateinit var grants: NativeGalleryFileGrantPolicy
        val activityController = Robolectric.buildActivity(ComponentActivity::class.java).setup()
        val activity: ComponentActivity get() = activityController.get()
        private val selections = mutableListOf<NativeGalleryReceiveConsent>()
        private val executor = Executors.newSingleThreadExecutor { Thread(it, "native-receive-policy-test").apply { isDaemon = true } }
        init {
            Shadows.shadowOf(app).denyPermissions(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO,
                Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE)
            connect()
        }
        private fun connect() {
            controller = GalleryReceivePolicyController(index, pc) { ticket?.let { session.receiveConfigurationAuthority(it) } }
            grants = NativeGalleryFileGrantPolicy({ peer }, { index.galleryPolicy() }, { true }, { handlerReady && controller.available() })
            session = NativeFileControlSession(phone, { peer }, { grants.current() }, { now }, { handlerReady && !sourceBusy })
            pcSession = NativeFileControlSession(pc, { pcPeer }, { pcLocal })
            handshake()
        }
        fun reconnect(pairing: String) {
            finishTicket(); session.close(); pcSession.close()
            peer = peer.copy(owner = Any(), pairingEpoch = pairing); pcPeer = pcPeer.copy(owner = Any(), pairingEpoch = pairing)
            pcLocal = NativeLocalFileGrant(DeviceFileGrantState(4, "c".repeat(64), true, true), Any(), true)
            connect()
        }
        fun handshake() {
            fun send(from: NativeFileControlSession, to: NativeFileControlSession, target: NativeFileControlPeer) {
                val packet = from.packet(); from.markSent(packet); to.observeRemote(DeviceFileControlPacket.parse(packet.wire()), target)
            }
            send(pcSession, session, peer); send(session, pcSession, pcPeer)
            if (pcSession.needsPacket()) send(pcSession, session, peer)
            if (session.needsPacket()) send(session, pcSession, pcPeer)
        }
        fun finishTicket() { ticket?.let { session.finishConfiguration(it) }; ticket = null }
        fun book() = NativeGalleryReceiveBookPermit.capture({ currentDocuments }) { unlocked }
        fun prompt(kind: GalleryMediaType = GalleryMediaType.IMAGES): Prompt {
            finishTicket(); handshake(); ticket = session.receiveConfigurationTicket()
            val scope = session.receiveConfigurationAuthority(ticket!!)!!
            val result = AtomicReference<Result<NativeGalleryReceiveConsent>?>()
            NativeGalleryReceiveConsent.request(activity, "Native own PC", kind, scope, book()) { result.set(it) }
            return Prompt(ShadowAlertDialog.getLatestAlertDialog(), result)
        }
        fun approve(kind: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryReceiveConsent {
            val prompt = prompt(kind); positive(prompt)
            return prompt.result.get()!!.getOrThrow().also { selections += it }
        }
        fun positive(prompt: Prompt) { prompt.dialog.getButton(DialogInterface.BUTTON_POSITIVE).performClick(); Shadows.shadowOf(Looper.getMainLooper()).idle() }
        fun <T> io(action: () -> T): T = try { executor.submit(Callable { action() }).get(10, TimeUnit.SECONDS) }
            catch (error: ExecutionException) { throw error.cause ?: error }
        fun rows(): Map<String, List<Byte>> = SQLiteDatabase.openDatabase(File(indexRoot, "photo-source-jobs.db").path, null,
            SQLiteDatabase.OPEN_READONLY).use { db ->
            buildMap { db.rawQuery("SELECT name,sealed FROM source_meta ORDER BY name", null).use { while (it.moveToNext()) put(it.getString(0), it.getBlob(1).toList()) } }
        }
        // Test-only boundary seed through the real protected writer/membership
        // transaction, never a production counter-reset/jump or SQL forgery.
        fun seedPolicy(policy: GalleryPhotoPolicy): GalleryPhotoPolicySnapshot {
            val name = "gallery-policy-v1"
            val clear = java.io.ByteArrayOutputStream().also { TelefonRahmen.schreiben(it, policy.wire(), DeviceTransferProtection.MAX_CLEAR_BYTES - 4) }.toByteArray()
            val sealed = protection.seal(clear, "photo-source-jobs-v1/$name")
            val put = PhotoSourceJobIndex::class.java.getDeclaredMethod("putMeta", String::class.java, ByteArray::class.java).also { it.isAccessible = true }
            val transaction = PhotoSourceJobIndex::class.java.declaredMethods.single { it.name == "transaction" }.also { it.isAccessible = true }
            val write: () -> Unit = { put.invoke(index, name, sealed); Unit }
            transaction.invoke(index, false, write)
            return index.galleryPolicy()
        }
        override fun close() {
            selections.forEach { it.close() }; finishTicket(); session.close(); pcSession.close()
            executor.shutdownNow(); check(executor.awaitTermination(5, TimeUnit.SECONDS)); index.close()
            activityController.pause().stop().destroy(); root.deleteRecursively()
        }
    }

    @Test fun realLocalPositiveButtonCommitsOnlyNativePhotoReceiveConsentAndDataStillNeedsFreshAck() {
        Fixture().use { f ->
            fun assertOsPermissionsDenied() {
                for (permission in listOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO,
                    Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE))
                    assertEquals(permission, PackageManager.PERMISSION_DENIED, f.app.checkSelfPermission(permission))
            }
            assertOsPermissionsDenied()
            val before = f.index.galleryPolicy(); val selection = f.approve()
            assertEquals(before, f.index.galleryPolicy()) // The dialog itself performs no policy IO.
            assertThrows(PhotoFolderScopeError::class.java) { f.controller.grant(before, selection) }
            val saved = f.io { f.controller.grant(before, selection) }; val policy = saved.policy!!
            assertFalse(policy.enabled); assertFalse(policy.videos!!.enabled)
            assertTrue(policy.receiving!!.photos); assertFalse(policy.receiving.videos)
            assertTrue(f.grants.current()!!.grants.receiveFiles); assertFalse(f.grants.current()!!.grants.sendFiles)
            assertNull(f.session.binding("c".repeat(64)))
            f.handshake(); assertNotNull(f.session.binding("c".repeat(64)))
            assertOsPermissionsDenied()
            val unsupported = NativeGalleryFileGrantPolicy({ f.peer }, { f.index.galleryPolicy() }, { true })
            assertNull("Stored consent cannot invent an absent receive handler", unsupported.current())
            assertThrows(PhotoFolderScopeError::class.java) { f.io { f.controller.grant(saved, selection) } }
            val again = f.approve(); assertEquals(saved, f.io { f.controller.grant(saved, again) })
        }
    }

    @Test fun cancelAndBookOrActivityTurnoverCannotCreateConsentOrDefaultPolicy() {
        for (change in listOf("cancel", "book", "pause")) Fixture().use { f ->
            val before = f.rows(); val prompt = f.prompt()
            when (change) {
                "cancel" -> { prompt.dialog.getButton(DialogInterface.BUTTON_NEGATIVE).performClick(); Shadows.shadowOf(Looper.getMainLooper()).idle() }
                "book" -> { f.documents.setzePapierkorb(true, 30); f.positive(prompt) }
                else -> { f.activityController.pause().resume(); f.positive(prompt) }
            }
            assertTrue(prompt.result.get()!!.isFailure); assertNull(f.index.galleryPolicy().policy); assertEquals(before, f.rows())
        }
    }

    @Test fun changedConfigurerExpiryOrBusySourceAfterPositiveIsHeldBeforePublication() {
        for (change in listOf("source_busy", "expired", "peer", "book", "profile")) Fixture().use { f ->
            val before = f.index.galleryPolicy(); val rows = f.rows(); val selected = f.approve()
            when (change) {
                "source_busy" -> f.sourceBusy = true
                "expired" -> f.now += DeviceFileControl.MAX_TTL_MS
                "peer" -> f.peer = f.peer.copy(ready = false)
                "profile" -> f.currentDocuments = null
                else -> f.documents.setzePapierkorb(true, 90)
            }
            assertThrows(PhotoFolderScopeError::class.java) { f.io { f.controller.grant(before, selected) } }
            assertEquals(rows, f.rows()); assertNull(f.index.galleryPolicy().policy)
            assertFalse(f.grants.current()?.grants?.receiveFiles == true)
        }
    }

    @Test fun localDecreaseNeedsNoLivePcAndNeverBootstrapsAbsentPolicyOrChangesSourceEpoch() {
        Fixture().use { f ->
            val absent = f.index.galleryPolicy(); val rows = f.rows()
            assertEquals(absent, f.io { f.controller.revoke(absent, GalleryMediaType.IMAGES, f.book()) }); assertEquals(rows, f.rows())
            val photos = f.approve(); val first = f.io { f.controller.grant(absent, photos) }
            val video = f.approve(GalleryMediaType.VIDEO); val both = f.io { f.controller.grant(first, video) }
            val sourceEpoch = both.policy!!.epoch; f.finishTicket(); f.session.close()
            val decreased = f.io { f.controller.revoke(both, GalleryMediaType.IMAGES, f.book()) }
            assertFalse(decreased.policy!!.receiving!!.photos); assertTrue(decreased.policy.receiving.videos)
            assertEquals(sourceEpoch, decreased.policy.epoch); assertFalse(decreased.policy.enabled)
            assertTrue(decreased.policy.fileGrantRevision > both.policy.fileGrantRevision)
            assertEquals(decreased, f.io { f.controller.revoke(decreased, GalleryMediaType.IMAGES, f.book()) })
        }
    }

    @Test fun sourceAndVideoConfigurationPreserveReceiveChoicesButRePairDoesNotInheritThem() {
        Fixture().use { f ->
            val photo = f.approve(); val saved = f.io { f.controller.grant(f.index.galleryPolicy(), photo) }
            f.finishTicket(); f.handshake(); val sourceTicket = f.session.configurationTicket(); f.ticket = sourceTicket
            val source = GalleryPhotoPolicyController.forAuthenticatedConfigurer(f.index, { f.session.photoReceiver() },
                { f.session.configurationAuthority(sourceTicket) })
            val enabled = f.io { source.configure(saved, true, setOf(GallerySourceKind.CAMERA)) }
            assertEquals(saved.policy!!.receiving, enabled.policy!!.receiving)
            f.handshake(); val grant = f.grants.current()!!.grants
            val video = f.io { source.configureVideos(enabled, true) }
            assertEquals(enabled.policy.receiving, video.policy!!.receiving); assertEquals(grant, f.grants.current()!!.grants)
            f.reconnect("a".repeat(64)); assertFalse(f.grants.current()!!.grants.receiveFiles)
            val approvedVideo = f.approve(GalleryMediaType.VIDEO)
            val repaired = f.io { f.controller.grant(video, approvedVideo) }
            assertFalse(repaired.policy!!.receiving!!.photos); assertTrue(repaired.policy.receiving.videos)
            assertFalse(repaired.policy.enabled); assertFalse(repaired.policy.videos!!.enabled)
        }
    }

    @Test fun receivingChangesNeedPermissionRevisionAndCannotBeDroppedByOldSourceWriters() {
        Fixture().use { f ->
            val selection = f.approve(); val saved = f.io { f.controller.grant(f.index.galleryPolicy(), selection) }; val p = saved.policy!!
            assertEquals(p, GalleryPhotoPolicy.parse(p.wire()))
            val noRevision = GalleryPhotoPolicy(p.receiverId, p.receiverIdentitySha256, p.epoch, p.enabled, p.kinds,
                p.revision + 1, 5, p.pairingEpoch, p.videos, p.fileGrantRevision, p.receiving!!.copy(videos = true))
            assertThrows(PhotoFolderScopeError::class.java) { f.io { f.index.compareAndSetGalleryPolicy(saved, noRevision) { true } } }
            val dropped = GalleryPhotoPolicy(p.receiverId, p.receiverIdentitySha256, p.epoch, p.enabled, p.kinds,
                p.revision + 1, 4, p.pairingEpoch, p.videos, p.revision + 1)
            assertThrows(PhotoFolderScopeError::class.java) { f.io { f.index.compareAndSetGalleryPolicy(saved, dropped) { true } } }
            assertEquals(saved, f.index.galleryPolicy())
        }
    }

    @Test fun interruptedConsentPublicationIsRepairPendingNotAnOffOrSuccessfulReceiveGrant() {
        Fixture().use { f ->
            val selected = f.approve(); val before = f.index.galleryPolicy()
            f.hook = { if (it == "gallery-policy-fenced") throw java.io.IOException("explicit test interruption") }
            assertThrows(java.io.IOException::class.java) { f.io { f.controller.grant(before, selected) } }
            assertTrue(f.index.galleryPolicy().repairPending); assertFalse(f.controller.available())
            assertNull(f.session.binding("c".repeat(64)))
            assertFalse(f.grants.current()?.policyReady == true)
        }
    }

    @Test fun exhaustedNativeDecreaseHoldsThisOwnerWithoutRollingCountersOrClaimingStoredOff() {
        Fixture().use { f ->
            val approved = f.approve(); val saved = f.io { f.controller.grant(f.index.galleryPolicy(), approved) }; val p = saved.policy!!
            val exhausted = f.seedPolicy(GalleryPhotoPolicy(p.receiverId, p.receiverIdentitySha256, p.epoch, p.enabled, p.kinds,
                DeviceFileControl.MAX_REVISION, 5, p.pairingEpoch, p.videos, DeviceFileControl.MAX_REVISION,
                p.receiving!!.copy(revision = DeviceFileControl.MAX_REVISION)))
            f.handshake(); assertNotNull(f.session.binding("c".repeat(64))); val before = f.rows()
            assertThrows(PhotoFolderScopeError::class.java) { f.io { f.controller.revoke(exhausted, GalleryMediaType.IMAGES, f.book()) } }
            assertFalse(f.controller.available()); assertNull(f.grants.current()); assertNull(f.session.binding("c".repeat(64)))
            assertEquals(before, f.rows()); assertEquals(exhausted, f.index.galleryPolicy()); assertTrue(exhausted.policy!!.receiving!!.photos)
        }
    }

    @Test @Config(sdk = [28]) fun unsupportedAndroidCannotObtainLocalPositiveReceiveSelection() {
        Fixture().use { f ->
            assertThrows(PhotoFolderScopeError::class.java) { f.prompt() }
            val before = f.index.galleryPolicy(); assertNull(before.policy)
            assertEquals(before, f.io { f.controller.revoke(before, GalleryMediaType.IMAGES, f.book()) })
        }
    }
}
