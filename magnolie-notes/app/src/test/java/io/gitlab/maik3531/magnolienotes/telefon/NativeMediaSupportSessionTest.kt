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

    @Test fun originalImageBatchHelloIsSeparateAndWithdrawsOnTheSameParent() {
        val peer = System.getenv("MAGNOLIE_TEST_PC_IMAGE_BATCH_PEER")?.let(::File)
        org.junit.Assume.assumeNotNull(peer)
        assertTrue(BuildConfig.PRIVATE_PC_IMAGE_BATCH_RECEIVE)
        pairedSession(testSettings = false, imageBatchPeer = checkNotNull(peer))
    }

    @Test
    @Config(shadows = [NativeIncomingMediaInspectionTest.FixtureLinux::class,
        GalleryIncomingRowsTest.SameFileDescriptorDuplicate::class])
    @org.robolectric.annotation.GraphicsMode(org.robolectric.annotation.GraphicsMode.Mode.NATIVE)
    fun originalImageBatchNeedsSeparatePhotoReceiveAndEndsOnTheDesktop() {
        val peer = System.getenv("MAGNOLIE_TEST_CONFIRMED_IMAGE_BATCH_PEER")?.let(::File)
        org.junit.Assume.assumeNotNull(peer)
        assertTrue(BuildConfig.PRIVATE_PC_IMAGE_BATCH_RECEIVE)
        pairedSession(testSettings = false, imageBatchPeer = checkNotNull(peer), sendImages = true)
    }

    private fun pairedSession(testSettings: Boolean, reconnect: Boolean = false, videoSender: Boolean = false,
        imageBatchPeer: File? = null, sendImages: Boolean = false) {
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
            val script = (imageBatchPeer ?: fullVideoPeer ?: File("../magnolie-organizer/pruefungen/media_support_paired_peer.py")).canonicalFile
            assertTrue(script.isFile)
            val command = listOf(System.getenv("MAGNOLIE_PYTHON") ?: "/usr/bin/python3", "-B", script.path) +
                when {
                    sendImages -> listOf("--pc-send-bootstrap")
                    imageBatchPeer != null -> listOf("--batch-support")
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
            val hostInput = process.outputStream.bufferedWriter()
            hostInput.write("${identity.device_id} ${identity.static_public}\n")
            hostInput.flush()
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
                        if (imageBatchPeer != null) {
                            assertEquals("image-batch-live", readHost())
                            val channel = field(TelefonWerk::class.java, "activeChannel").get(work) as TelefonSecureChannel
                            fun attempts(): Pair<NativeMediaSupportAttempt, NativeMediaSupportAttempt> {
                                val activeReader = synchronized(work) {
                                    (field(TelefonWerk::class.java, "mediaSupportReaders").get(work) as Map<*, *>)[channel]
                                } ?: error("Original support reader vanished")
                                return (field(activeReader.javaClass, "attempt").get(activeReader) as NativeMediaSupportAttempt) to
                                    (field(activeReader.javaClass, "imageBatch").get(activeReader) as NativeMediaSupportAttempt)
                            }
                            val (shared, batch) = attempts()
                            assertNotSame(shared, batch)
                            assertEquals(NativeMediaSupportAttempt.SHARED_SETTINGS, shared.feature)
                            assertEquals(NativeMediaSupportAttempt.PC_IMAGE_BATCH, batch.feature)
                            assertTrue(shared.supports(channel)); assertTrue(batch.supports(channel))
                            assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
                            assertFalse(work.state.value.privatePcImageReceiveReady)
                            if (sendImages) {
                                fun command(message: String) { hostInput.write("$message\n"); hostInput.flush() }
                                command("start-send-bootstrap")
                                assertEquals("pc-send-intent-ready", readHost())
                                assertTrue(work.state.value.mediaPreferencesReady)
                                assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
                                command("enable-pc-send-controls")
                                assertEquals("pc-send-controls-closed", readHost(pumpUi = true))
                                awaitUi(8) { work.state.value.privatePcImageReceiveReady }
                                assertFalse(work.state.value.privatePcVideoReceiveReady)
                                val owner = field(TelefonWerk::class.java, "galleryFileConnection").get(work) as NativeGalleryFileConnection
                                assertSame(channel, owner.channel)
                                assertNull(owner.runtime.savedPolicy().policy)
                                confirmImageReceiving(work, owner)
                                assertEquals("pc-send-receive-confirmed", readHost())

                                GalleryIncomingRowsTest().mountedPrimaryVolume()
                                val originals = listOf(png(0xff507991.toInt()), png(0xff314820.toInt()))
                                assertFalse("The native PNG fixture must yield different originals",
                                    originals[0].contentEquals(originals[1]))
                                val files = originals.indices.map { File(context.cacheDir, "published-original-${it + 1}.png") }
                                val providers = files.mapIndexed { index, file ->
                                    GalleryIncomingRowsTest.Provider(context as Application, payload = file, rowId = 99L + index)
                                        .apply { allowPublish = true }
                                }
                                ShadowContentResolver.registerProviderInternal("media", GalleryIncomingRowsTest.BatchProvider(context as Application,
                                    providers.mapIndexed { index, provider -> "original-${index + 1}.png" to provider }.toMap(),
                                    providers.mapIndexed { index, provider -> (99 + index).toString() to provider }.toMap()))
                                val encoded = originals.joinToString(" ", transform = java.util.Base64.getEncoder()::encodeToString)
                                command("publish-original $encoded")
                                assertEquals("original-batch-accepted", readHost(seconds = 38))
                                command("continue-original-batch")
                                assertEquals("original-batch-archived-end", readHost(seconds = 50))
                                command("check-unchanged-root")
                                assertEquals("unchanged-root-no-output", readHost(seconds = 38))
                                for (i in originals.indices) {
                                    assertArrayEquals(originals[i], files[i].readBytes())
                                    assertEquals(1, providers[i].inserts)
                                    assertEquals(1, providers[i].publishes)
                                    assertEquals(0, providers[i].rwOpens)
                                }
                            }
                            hostInput.write("withdraw-batch-probe\n"); hostInput.flush()
                            assertEquals("image-batch-withdrawn", readHost())
                            assertSame(channel, field(TelefonWerk::class.java, "activeChannel").get(work))
                            assertFalse(batch.supports(channel))
                            assertFalse(work.state.value.privatePcImageReceiveReady)
                            hostInput.write("close-batch-probe\n"); hostInput.flush()
                        }
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
                if (videoSender || sendImages)
                    awaitUi(5) { field(TelefonWerk::class.java, "galleryFileConnection").get(work) == null }
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

    private fun confirmImageReceiving(work: TelefonWerk, owner: NativeGalleryFileConnection) {
        val activity = Robolectric.buildActivity(ComponentActivity::class.java).setup()
        val scope = CoroutineScope(Dispatchers.Main.immediate + SupervisorJob())
        try {
            for (approve in listOf(false, true)) {
                val result = AtomicReference<Result<GalleryPhotoPolicySnapshot>?>()
                val previous = ShadowAlertDialog.getLatestAlertDialog()
                val choice = scope.launch {
                    result.set(runCatching { work.allowMediaReceiving(activity.get(), GalleryMediaType.IMAGES) })
                }
                awaitUi(8) { result.get() != null || ShadowAlertDialog.getLatestAlertDialog() !== previous }
                result.get()?.getOrThrow()
                assertNull(owner.runtime.savedPolicy().policy)
                val dialog = ShadowAlertDialog.getLatestAlertDialog()
                dialog.getButton(if (approve) DialogInterface.BUTTON_POSITIVE else DialogInterface.BUTTON_NEGATIVE).performClick()
                awaitUi(8) { choice.isCompleted }
                if (approve) result.get()!!.getOrThrow()
                val policy = owner.runtime.savedPolicy().policy
                assertEquals(approve, policy?.receiving?.photos == true)
                assertFalse(policy?.receiving?.videos == true)
                assertFalse(policy?.enabled == true)
            }
        } finally {
            scope.cancel()
            activity.pause().stop().destroy()
        }
    }

    private fun png(color: Int): ByteArray {
        val bitmap = android.graphics.Bitmap.createBitmap(32, 32, android.graphics.Bitmap.Config.ARGB_8888)
        return try {
            bitmap.eraseColor(color)
            java.io.ByteArrayOutputStream().use {
                check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it))
                it.toByteArray()
            }
        } finally { bitmap.recycle() }
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
