package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import android.content.DialogInterface
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.BuildConfig
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import java.io.File
import java.security.Provider
import java.security.Security
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.spec.SecretKeySpec
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import org.robolectric.shadows.ShadowAlertDialog
import org.robolectric.shadows.ShadowContentResolver

/** Real paired-session readers and control warm-up, with disposable pins and loopback TCP. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class NativeMediaSupportSessionTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun phoneInitiatesOnlyAfterWarmupAndLinuxCompletesOnSamePairing() = pairedSession(testSettings = false)

    @Test fun phoneAndLinuxAgreeOnSettingsWithoutStartingTransfer() = pairedSession(testSettings = true)

    @Test fun originalPairingKeepsSettingsButRequiresNewAgreementOnReconnect() = pairedSession(testSettings = true, reconnect = true)

    @Test @Config(shadows = [NativeIncomingMediaInspectionTest.FixtureLinux::class])
    fun matchedVideoSenderWithoutReceiveGetsOnlyAClosedNotesOwner() =
        pairedSession(testSettings = true, videoSender = true)

    private fun pairedSession(testSettings: Boolean, reconnect: Boolean = false, videoSender: Boolean = false) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("MediaSessionFixture", 1.0, "Isolated test keys") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        val documents = field(Ablage::class.java, "einzig")
        val originalDocuments = documents.get(null)
        val tasks = Executors.newFixedThreadPool(2)
        val errors = File.createTempFile("media-support-peer", ".log", context.cacheDir)
        var host: Process? = null
        var werk: TelefonWerk? = null
        assertEquals(1, Security.insertProviderAt(provider, 1))
        try {
            documents.set(null, Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") })
            val storage = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java)
                .apply { isAccessible = true }.newInstance(context)
            val (identity, secret) = storage.identity("Isolated phone"); secret.fill(0)
            storage.setEnabled(true)
            storage.setPersonalSync(true, false, false, false, false)
            val fullVideoPeer = if (videoSender) System.getenv("MAGNOLIE_TEST_TYPED_VIDEO_PEER")?.let(::File) else null
            val script = (fullVideoPeer ?: File("../magnolie-organizer/pruefungen/media_support_paired_peer.py")).canonicalFile
            assertTrue(script.isFile)
            val command = listOf(System.getenv("MAGNOLIE_PYTHON") ?: "/usr/bin/python3", "-B", script.path) +
                when {
                    fullVideoPeer != null -> listOf("--pc-send-typed-video")
                    videoSender -> listOf("--video-sender")
                    reconnect -> listOf("--reconnect")
                    testSettings -> listOf("--settings")
                    else -> emptyList()
                }
            val process = ProcessBuilder(command)
                .redirectError(errors).start().also { host = it }
            val stdout = process.inputStream.bufferedReader()
            fun readHost(pumpUi: Boolean = false, seconds: Long = 20): String {
                val response = tasks.submit<String> { checkNotNull(stdout.readLine()) { errors.readText() } }
                if (pumpUi) awaitUi(seconds) { response.isDone }
                return response.get(if (pumpUi) 0 else seconds, TimeUnit.SECONDS)
            }
            val (port, desktopId, publicKey) = readHost().split(' ')
            val peer = TelefonPeer(desktopId, "Isolated desktop", publicKey, own_device = true, remote_own_device = true,
                file_pairing_epoch = "a".repeat(64))
            storage.savePeer(peer)
            process.outputStream.bufferedWriter().use { it.write("${identity.device_id} ${identity.static_public}\n") }
            val work = TelefonWerk::class.java.getDeclaredConstructor(Context::class.java, TelefonAblage::class.java)
                .apply { isAccessible = true }.newInstance(context, storage).also { werk = it }
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
            field(TelefonWerk::class.java, "nativeMediaSupportChecked").setBoolean(work, true)
            if (fullVideoPeer != null) assertTrue(BuildConfig.PRIVATE_PC_VIDEO_RECEIVE)
            else if (videoSender) field(TelefonWerk::class.java, "nativePcVideoReceiveChecked").setBoolean(work, true)
            val fixture = if (fullVideoPeer != null) NativeGalleryIncomingRuntimeTest() else null
            val published = if (fixture != null) File(context.cacheDir, "paired-original.mp4") else null
            val gallery = if (fixture != null && published != null) {
                GalleryIncomingRowsTest().mountedPrimaryVolume()
                GalleryIncomingRowsTest.Provider(context as Application, GalleryMediaType.VIDEO, published).apply {
                    allowPublish = true
                    fixture.prepareVideoMetadata(this, published)
                    ShadowContentResolver.registerProviderInternal("media", this)
                }
            } else null
            (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
            val session = TelefonWerk::class.java.getDeclaredMethod("session", TelefonPeer::class.java,
                TelefonTransportArt::class.java, TelefonRoehre::class.java, String::class.java, String::class.java,
                Boolean::class.javaPrimitiveType, kotlin.jvm.functions.Function0::class.java).apply { isAccessible = true }
            repeat(if (reconnect) 2 else 1) {
                TelefonTcpRoehre("127.0.0.1", port = port.toInt()).use { pipe ->
                    pipe.setReadTimeout(if (fullVideoPeer == null) 15_000 else 55_000)
                    val reader = tasks.submit { session.invoke(work, peer, TelefonTransportArt.WIFI, pipe, "", "", false, {}) }
                    try {
                        if (gallery != null && fixture != null && published != null) {
                            assertEquals("video-closed-owner", readHost(pumpUi = true))
                            awaitUi(12) { work.state.value.privatePcVideoReceiveReady }
                            assertTrue(work.state.value.mediaPreferencesReady)
                            val owner = field(TelefonWerk::class.java, "galleryFileConnection").get(work) as NativeGalleryFileConnection
                            assertNull(owner.runtime.savedPolicy().policy)
                            assertEquals(0, gallery.inserts)
                            val activity = Robolectric.buildActivity(ComponentActivity::class.java).setup()
                            val scope = CoroutineScope(Dispatchers.Main.immediate + SupervisorJob())
                            val result = AtomicReference<Result<GalleryPhotoPolicySnapshot>?>()
                            try {
                                val previous = ShadowAlertDialog.getLatestAlertDialog()
                                val choice = scope.launch {
                                    result.set(runCatching { work.allowMediaReceiving(activity.get(), GalleryMediaType.VIDEO) })
                                }
                                awaitUi(8) { result.get() != null || ShadowAlertDialog.getLatestAlertDialog() !== previous }
                                result.get()?.getOrThrow()
                                assertNull(owner.runtime.savedPolicy().policy)
                                ShadowAlertDialog.getLatestAlertDialog().getButton(DialogInterface.BUTTON_POSITIVE).performClick()
                                awaitUi(8) { choice.isCompleted }
                                val receiving = result.get()!!.getOrThrow().policy?.receiving
                                assertTrue(receiving?.videos == true)
                                assertFalse(receiving?.photos == true)
                            } finally {
                                scope.cancel()
                                activity.pause().stop().destroy()
                            }
                            assertEquals("video-archived-end-unchanged", readHost(pumpUi = true, seconds = 48))
                            assertArrayEquals(fixture.originalMp4(), published.readBytes())
                            assertEquals(1, gallery.inserts)
                            assertEquals(1, gallery.publishes)
                            assertEquals(0, gallery.rwOpens)
                        }
                        assertEquals("same-parent-pong", readHost(pumpUi = videoSender))
                        reader.get(5, TimeUnit.SECONDS)
                    } catch (error: Exception) {
                        val galleryProgress = gallery?.let {
                            " Gallery progress: inserts=${it.inserts}, writes=${it.writeOpens}, publications=${it.publishes}, reads=${it.readOpens}."
                        }.orEmpty()
                        val failure = AssertionError("Paired media test failed.$galleryProgress Desktop stderr:\n${errors.readText()}", error)
                        if (reader.isDone) runCatching { reader.get() }.exceptionOrNull()?.let { failure.addSuppressed(it) }
                        throw failure
                    }
                }
                assertTrue((field(TelefonWerk::class.java, "mediaSupportReaders").get(work) as Map<*, *>).isEmpty())
                if (videoSender) Shadows.shadowOf(Looper.getMainLooper()).idle()
                assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
                assertFalse(work.state.value.mediaPreferencesSupported)
                assertEquals(peer.file_pairing_epoch, storage.fileAuthorityPeers().peer?.file_pairing_epoch)
                if (videoSender) assertTrue(DeviceFileControl.VIDEO_DISCOVERY_VERSION in
                    storage.fileAuthorityPeers().peer!!.remote_device_status_versions)
                if (testSettings) {
                    val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
                    val db = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).readableDatabase
                    db.rawQuery("SELECT COUNT(*) FROM native_media_shared_settings WHERE peer_id=?", arrayOf(desktopId)).use {
                        assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
                    }
                }
            }
            assertTrue(errors.readText(), process.waitFor(4, TimeUnit.SECONDS) && process.exitValue() == 0)
        } finally {
            werk?.serviceStopped()
            host?.let { it.destroy(); if (!it.waitFor(2, TimeUnit.SECONDS)) it.destroyForcibly() }
            tasks.shutdownNow()
            documents.set(null, originalDocuments)
            Security.removeProvider(provider.name)
        }
    }

    private fun awaitUi(seconds: Long, ready: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(seconds)
        while (!ready()) {
            Shadows.shadowOf(Looper.getMainLooper()).idle()
            check(System.nanoTime() < deadline) { "Paired Notes UI deadline expired" }
            Thread.sleep(5)
        }
    }
}
