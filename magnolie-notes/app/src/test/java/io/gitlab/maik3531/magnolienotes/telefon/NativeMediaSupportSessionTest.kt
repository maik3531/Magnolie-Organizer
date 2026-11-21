package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import java.io.File
import java.security.Provider
import java.security.Security
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode

/** Real paired-session readers and control warm-up, with disposable pins and loopback TCP. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class NativeMediaSupportSessionTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun phoneInitiatesOnlyAfterWarmupAndLinuxCompletesOnSamePairing() = pairedSession(testSettings = false)

    @Test fun phoneAndLinuxAgreeOnSettingsWithoutStartingTransfer() = pairedSession(testSettings = true)

    private fun pairedSession(testSettings: Boolean) {
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
            val script = File("../magnolie-organizer/pruefungen/media_support_paired_peer.py").canonicalFile
            assertTrue(script.isFile)
            val command = listOf(System.getenv("MAGNOLIE_PYTHON") ?: "/usr/bin/python3", "-B", script.path) +
                if (testSettings) listOf("--settings") else emptyList()
            val process = ProcessBuilder(command)
                .redirectError(errors).start().also { host = it }
            val stdout = process.inputStream.bufferedReader()
            fun readHost(): String = tasks.submit<String> { checkNotNull(stdout.readLine()) { errors.readText() } }
                .get(20, TimeUnit.SECONDS)
            val (port, desktopId, publicKey) = readHost().split(' ')
            val peer = TelefonPeer(desktopId, "Isolated desktop", publicKey, own_device = true, remote_own_device = true,
                file_pairing_epoch = "a".repeat(64))
            storage.savePeer(peer)
            process.outputStream.bufferedWriter().use { it.write("${identity.device_id} ${identity.static_public}\n") }
            val work = TelefonWerk::class.java.getDeclaredConstructor(Context::class.java, TelefonAblage::class.java)
                .apply { isAccessible = true }.newInstance(context, storage).also { werk = it }
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
            field(TelefonWerk::class.java, "nativeMediaSupportChecked").setBoolean(work, true)
            (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
            val session = TelefonWerk::class.java.getDeclaredMethod("session", TelefonPeer::class.java,
                TelefonTransportArt::class.java, TelefonRoehre::class.java, String::class.java, String::class.java,
                Boolean::class.javaPrimitiveType, kotlin.jvm.functions.Function0::class.java).apply { isAccessible = true }
            TelefonTcpRoehre("127.0.0.1", port = port.toInt()).use { pipe ->
                pipe.setReadTimeout(15_000)
                val reader = tasks.submit { session.invoke(work, peer, TelefonTransportArt.WIFI, pipe, "", "", false, {}) }
                try {
                    assertEquals("same-parent-pong", readHost())
                    reader.get(5, TimeUnit.SECONDS)
                } catch (error: Exception) {
                    val failure = AssertionError("Paired media test failed. Desktop stderr:\n${errors.readText()}", error)
                    if (reader.isDone) runCatching { reader.get() }.exceptionOrNull()?.let { failure.addSuppressed(it) }
                    throw failure
                }
            }
            assertTrue(errors.readText(), process.waitFor(4, TimeUnit.SECONDS) && process.exitValue() == 0)
            assertTrue((field(TelefonWerk::class.java, "mediaSupportReaders").get(work) as Map<*, *>).isEmpty())
            assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
            assertFalse(work.state.value.mediaPreferencesSupported)
            assertEquals(peer.file_pairing_epoch, storage.fileAuthorityPeers().peer?.file_pairing_epoch)
        } finally {
            werk?.serviceStopped()
            host?.let { it.destroy(); if (!it.waitFor(2, TimeUnit.SECONDS)) it.destroyForcibly() }
            tasks.shutdownNow()
            documents.set(null, originalDocuments)
            Security.removeProvider(provider.name)
        }
    }
}
