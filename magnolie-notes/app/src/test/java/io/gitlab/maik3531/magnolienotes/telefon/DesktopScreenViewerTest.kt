package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.app.Dialog
import android.app.KeyguardManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.drawable.BitmapDrawable
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.channels.ServerSocketChannel
import java.nio.channels.SocketChannel
import java.security.Provider
import java.security.Security
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowDialog

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class DesktopScreenViewerTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }
    private class Fixture(mode: Int = 1, nanosRemaining: Long = TimeUnit.SECONDS.toNanos(10)) : AutoCloseable {
        val controller = Robolectric.buildActivity(ComponentActivity::class.java).setup()
        val activity = controller.get()
        var live = true
        var approvals = 0
        var stops = 0
        val viewer = DesktopScreenViewer(activity, "Paired desktop", mode, 57, 33,
            System.nanoTime() + nanosRemaining, { check(live) }, { approvals++ }, { stops++ })

        fun show(): Dialog {
            viewer.show()
            return checkNotNull(ShadowDialog.getLatestDialog()).also { check(it.isShowing) }
        }

        fun button(dialog: Dialog, label: Int): Button = views(dialog.window!!.decorView)
            .filterIsInstance<Button>().single { it.text.toString() == activity.getString(label) }

        fun lock() { shadowOf(activity.getSystemService(KeyguardManager::class.java)).setIsDeviceLocked(true) }

        override fun close() {
            viewer.close()
            shadowOf(activity.getSystemService(KeyguardManager::class.java)).setIsDeviceLocked(false)
            controller.destroy()
        }
    }

    @Test fun explicitConfirmationIdentifiesOriginalOfferAndDismissalCannotReviveIt() {
        Fixture(mode = 2).use { f ->
            val dialog = f.show()
            val text = views(dialog.window!!.decorView).filterIsInstance<TextView>()
                .single { it.text.toString().contains("Paired desktop") }
            assertEquals(f.activity.getString(R.string.desktop_screen_extend_prompt, "Paired desktop"), text.text)
            assertTrue(dialog.window!!.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
            assertEquals(0, f.approvals)
            assertThrows(IllegalStateException::class.java) { f.viewer.requireViewing() }
            val accept = f.button(dialog, R.string.desktop_screen_view_accept)
            accept.performClick()
            accept.performClick()
            assertEquals(1, f.approvals)
            f.viewer.requireViewing()
            f.button(dialog, R.string.desktop_screen_view_stop).performClick()
            assertEquals(1, f.stops)
            assertFalse(dialog.isShowing)
            assertThrows(IllegalStateException::class.java) { f.viewer.requireViewing() }
            assertThrows(IllegalStateException::class.java) { f.viewer.show() }
        }
    }

    @Test fun locksPausesAndStaleOriginalDenyApprovalOrClearViewer() {
        Fixture().use { f ->
            val dialog = f.show()
            f.lock()
            f.button(dialog, R.string.desktop_screen_view_accept).performClick()
            assertEquals(0, f.approvals)
            assertEquals(1, f.stops)
        }
        Fixture().use { f ->
            val dialog = f.show()
            f.button(dialog, R.string.desktop_screen_view_accept).performClick()
            f.lock()
            shadowOf(Looper.getMainLooper()).idleFor(55, TimeUnit.MILLISECONDS)
            assertEquals(1, f.stops)
            assertFalse(dialog.isShowing)
            assertThrows(IllegalStateException::class.java) { f.viewer.requireViewing() }
        }
        Fixture().use { f ->
            val dialog = f.show()
            f.button(dialog, R.string.desktop_screen_view_accept).performClick()
            f.controller.pause().resume()
            assertEquals(1, f.stops)
            assertFalse(dialog.isShowing)
            assertThrows(IllegalStateException::class.java) { f.viewer.requireViewing() }
        }
        Fixture().use { f ->
            val dialog = f.show()
            f.live = false
            f.button(dialog, R.string.desktop_screen_view_accept).performClick()
            assertEquals(0, f.approvals)
            assertEquals(1, f.stops)
        }
        Fixture(nanosRemaining = -1).use { f ->
            assertThrows(IllegalStateException::class.java) { f.viewer.show() }
            assertEquals(1, f.stops)
        }
    }

    @Test fun nativeDecodeShowsOnlyLatestFrameAndHeartbeatDoesNotReplaceIt() {
        Fixture().use { f ->
            val dialog = f.show()
            val display = views(dialog.window!!.decorView).filterIsInstance<ImageView>()
                .single { it.contentDescription == f.activity.getString(R.string.desktop_screen_view_picture) }
            assertEquals(View.GONE, display.visibility)
            f.button(dialog, R.string.desktop_screen_view_accept).performClick()
            val first = jpeg(Color.RED)
            val latest = jpeg(Color.GREEN)
            f.viewer.offer(first)
            f.viewer.offer(latest)
            assertTrue(first.all { it == 0.toByte() } && latest.all { it == 0.toByte() })
            shadowOf(Looper.getMainLooper()).idleFor(55, TimeUnit.MILLISECONDS)
            val drawn = (display.drawable as BitmapDrawable).bitmap
            val pixel = drawn.getPixel(28, 16)
            assertTrue(Color.green(pixel) >= 240 && Color.red(pixel) <= 12)
            f.viewer.offer(ByteArray(0))
            shadowOf(Looper.getMainLooper()).idleFor(55, TimeUnit.MILLISECONDS)
            assertSame(drawn, (display.drawable as BitmapDrawable).bitmap)
            val wrong = jpeg(Color.RED, 58)
            assertThrows(IllegalArgumentException::class.java) { f.viewer.offer(wrong) }
            assertTrue(wrong.all { it == 0.toByte() })
            assertEquals(1, f.stops)
            assertNull(display.drawable)
        }
    }

    @Test fun joinedAttemptConnectsOnlyOnClickAndRetiresLateSocketAfterPause() {
        Fixture().use { f ->
            val entered = CountDownLatch(1)
            val release = CountDownLatch(1)
            val connections = AtomicInteger(0)
            val parent = Any()
            SocketChannel.open().use { original ->
                val attempt = DesktopScreenReceiveAttempt(f.activity, "Paired desktop", parent, ByteArray(16), ByteArray(32),
                    1, 57, 33, System.nanoTime() + TimeUnit.SECONDS.toNanos(7), {},
                    { guard ->
                        guard()
                        connections.incrementAndGet()
                        entered.countDown()
                        check(release.await(2, TimeUnit.SECONDS))
                        original
                    }, { _, _ -> error("Retired socket must not publish PREPARED") })
                try {
                    attempt.show()
                    val dialog = checkNotNull(ShadowDialog.getLatestDialog())
                    assertEquals(0, connections.get())
                    assertFalse(attempt.acceptSend(parent, ByteArray(32)))
                    f.button(dialog, R.string.desktop_screen_view_accept).performClick()
                    assertTrue(entered.await(1, TimeUnit.SECONDS))
                    f.controller.pause()
                    assertFalse(dialog.isShowing)
                    assertFalse(attempt.drained)
                    release.countDown()
                    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2)
                    while (!attempt.drained && System.nanoTime() - deadline < 0) Thread.sleep(5)
                    assertTrue(attempt.drained)
                    assertFalse(original.isOpen)
                    assertEquals(1, connections.get())
                    f.controller.resume()
                    assertFalse(attempt.acceptSend(parent, ByteArray(32)))
                    assertThrows(IllegalStateException::class.java) { attempt.show() }
                } finally {
                    release.countDown()
                    attempt.close()
                }
            }
        }
    }

    @Test fun joinedAttemptShowsAuthenticatedPixelAndClearsItOnPause() {
        Fixture().use { f ->
            ServerSocketChannel.open().use { server ->
                server.bind(InetSocketAddress(InetAddress.getLoopbackAddress(), 0))
                server.configureBlocking(false)
                val parent = Any()
                val prepared = ArrayBlockingQueue<ByteArray>(1)
                val attempt = DesktopScreenReceiveAttempt(f.activity, "Paired desktop", parent, DesktopScreenDraftPeer.session(),
                    DesktopScreenDraftPeer.secret(), 2, 57, 33, System.nanoTime() + TimeUnit.SECONDS.toNanos(6), { check(f.live) },
                    { guard -> guard(); SocketChannel.open(server.localAddress) },
                    { receipt, guard -> guard(); check(prepared.offer(receipt)) })
                attempt.use {
                    attempt.show()
                    val dialog = checkNotNull(ShadowDialog.getLatestDialog())
                    val display = views(dialog.window!!.decorView).filterIsInstance<ImageView>()
                        .single { it.contentDescription == f.activity.getString(R.string.desktop_screen_view_picture) }
                    f.button(dialog, R.string.desktop_screen_view_accept).performClick()
                    val desktop = awaitValue { server.accept() }
                    desktop.use {
                        desktop.socket().soTimeout = 1500
                        val digest = DesktopScreenDraftPeer.respond(desktop)
                        assertArrayEquals(digest, prepared.poll(1, TimeUnit.SECONDS))
                        assertNull(display.drawable)
                        assertTrue(attempt.acceptSend(parent, digest))
                        desktop.socket().getOutputStream().write(DesktopScreenDraftPeer.record(jpeg(Color.BLUE), 0))
                        val drawn = awaitValue {
                            shadowOf(Looper.getMainLooper()).idleFor(55, TimeUnit.MILLISECONDS)
                            (display.drawable as? BitmapDrawable)?.bitmap
                        }
                        val pixel = drawn.getPixel(28, 16)
                        assertTrue(Color.blue(pixel) >= 240 && Color.green(pixel) <= 12)
                        f.controller.pause()
                        assertNull(display.drawable)
                        assertFalse(dialog.isShowing)
                        awaitValue { true.takeIf { attempt.drained } }
                        assertEquals(-1, desktop.socket().getInputStream().read())
                    }
                }
            }
        }
    }

    @Test fun productionSessionsAuthenticateThenDeliverDesktopDraftAndKeepNotesParent() = pairedSession(false)

    @Test fun productionSessionsDesktopStopWithdrawsPendingApprovalAndKeepsNotesParent() = pairedSession(true)

    @Test fun productionSessionsAcceptDraftWhenDesktopClockIsTwoSecondsBehind() = pairedSession(false, true)

    private fun pairedSession(stopBeforePhoneApproval: Boolean, desktopClockBehind: Boolean = false) {
        assumeTrue(System.getenv("MAGNOLIE_DESKTOP_SCREEN_INTEROP") == "1")
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("DesktopDraftFixture", 1.0, "Isolated test keys") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        assertEquals(1, Security.insertProviderAt(provider, 1))
        val storageField = field(TelefonAblage::class.java, "instance")
        val workField = field(TelefonWerk::class.java, "instance")
        val documentsField = field(Ablage::class.java, "einzig")
        val oldDocuments = documentsField.get(null)
        val oldStorage = storageField.get(null)
        val oldWork = workField.get(null)
        val threads = Executors.newFixedThreadPool(2)
        val stderr = File.createTempFile("draft-peer", ".log", context.cacheDir)
        var server: Process? = null
        var work: TelefonWerk? = null
        try {
            documentsField.set(null, Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") })
            storageField.set(null, null)
            workField.set(null, null)
            val storage = TelefonAblage.get(context)
            val (identity, _) = storage.identity("Isolated phone")
            storage.setEnabled(true)
            storage.setPersonalSync(false, false, false, false, false)
            val script = File("../magnolie-organizer/pruefungen/desktop_screen_draft_paired_peer.py").canonicalFile
            assertTrue(script.isFile)
            val command = buildList {
                addAll(listOf("/usr/bin/python3", "-B", script.path))
                if (stopBeforePhoneApproval) add("--desktop-stop-before-phone-approval")
                if (desktopClockBehind) add("--desktop-clock-behind")
            }
            val process = ProcessBuilder(command)
                .redirectError(stderr).start()
            server = process
            val output = process.inputStream.bufferedReader()
            fun readHost() = threads.submit<String> { checkNotNull(output.readLine()) { "paired test host exited" } }
                .get(10, TimeUnit.SECONDS)
            val (port, desktopId, publicKey) = readHost().split(' ')
            val peer = TelefonPeer(desktopId, "Isolated desktop", publicKey)
            storage.savePeer(peer)
            val input = process.outputStream.bufferedWriter()
            input.write("${identity.device_id} ${identity.static_public}\n")
            input.flush()
            val runtime = TelefonWerk.get(context).also { work = it }
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(runtime, true)
            (field(TelefonWerk::class.java, "connecting").get(runtime) as AtomicBoolean).set(true)
            val session = TelefonWerk::class.java.getDeclaredMethod("session", TelefonPeer::class.java,
                TelefonTransportArt::class.java, TelefonRoehre::class.java, String::class.java, String::class.java,
                Boolean::class.javaPrimitiveType, kotlin.jvm.functions.Function0::class.java).apply { isAccessible = true }
            Fixture().use { f ->
                TelefonTcpRoehre("127.0.0.1", port = port.toInt()).use { pipe ->
                    pipe.setReadTimeout(20_000)
                    val reader = threads.submit {
                        session.invoke(runtime, peer, TelefonTransportArt.WIFI, pipe, "", "", false, {})
                    }
                    assertEquals("armed", readHost())
                    val original = awaitValue {
                        if (reader.isDone) reader.get() // Surface the session failure without waiting for a viewer.
                        runCatching { runtime.desktopScreenDraftCandidate(desktopId, publicKey) }.getOrNull()
                    }
                    runtime.beginDesktopScreenDraft(f.activity, original, 2).use { attempt ->
                        val dialog = awaitValue {
                            if (reader.isDone) reader.get()
                            shadowOf(Looper.getMainLooper()).idleFor(30, TimeUnit.MILLISECONDS)
                            ShadowDialog.getLatestDialog()?.takeIf { it.isShowing }
                        }
                        val image = views(dialog.window!!.decorView).filterIsInstance<ImageView>()
                            .single { it.contentDescription == f.activity.getString(R.string.desktop_screen_view_picture) }
                        assertNull(image.drawable)
                        if (stopBeforePhoneApproval) {
                            input.write("stop\n")
                            input.flush()
                            val accept = f.button(dialog, R.string.desktop_screen_view_accept)
                            awaitValue {
                                shadowOf(Looper.getMainLooper()).idleFor(30, TimeUnit.MILLISECONDS)
                                true.takeIf { !dialog.isShowing }
                            }
                            accept.performClick() // Stale confirmation must not reanimate this viewer.
                        } else {
                            f.button(dialog, R.string.desktop_screen_view_accept).performClick()
                            val drawn = awaitValue {
                                if (reader.isDone) reader.get()
                                shadowOf(Looper.getMainLooper()).idleFor(30, TimeUnit.MILLISECONDS)
                                (image.drawable as? BitmapDrawable)?.bitmap
                            }
                            assertTrue(kotlin.math.abs(Color.blue(drawn.getPixel(28, 16)) - 228) <= 4)
                            f.controller.pause()
                        }
                        assertNull(image.drawable)
                        assertFalse(dialog.isShowing)
                        awaitValue { true.takeIf { attempt.drained } }
                    }
                    assertEquals("same-parent-pong", readHost())
                    reader.get(5, TimeUnit.SECONDS)
                    assertTrue(runCatching { runtime.desktopScreenDraftCandidate(desktopId, publicKey) }.isFailure)
                }
            }
            input.close()
            assertTrue(process.waitFor(5, TimeUnit.SECONDS))
            assertEquals(0, process.exitValue())
        } catch (failure: Exception) {
            throw AssertionError(stderr.readText().take(4000), failure)
        } finally {
            server?.let { if (it.isAlive) it.destroyForcibly().waitFor(5, TimeUnit.SECONDS) }
            threads.shutdownNow()
            work?.serviceStopped()
            workField.set(null, oldWork)
            storageField.set(null, oldStorage)
            documentsField.set(null, oldDocuments)
            Security.removeProvider(provider.name)
            stderr.delete()
        }
    }

    @Test fun encryptedDraftAgainstLinuxReachesNativeViewerAndStopsWithoutClosingParent() {
        assumeTrue(System.getenv("MAGNOLIE_DESKTOP_SCREEN_INTEROP") == "1")
        val script = File("../magnolie-organizer/pruefungen/desktop_screen_draft_interop_peer.py").canonicalFile
        assertTrue(script.isFile)
        val server = ProcessBuilder("/usr/bin/python3", "-B", script.path)
            .redirectError(ProcessBuilder.Redirect.INHERIT).start()
        val readers = Executors.newSingleThreadExecutor()
        try {
            val port = readers.submit<Int> { checkNotNull(server.inputStream.bufferedReader().readLine()).toInt() }
                .get(4, TimeUnit.SECONDS)
            Fixture().use { f ->
                TelefonTcpRoehre("127.0.0.1", port = port).use { pipe ->
                    pipe.setReadTimeout(4_000)
                    TelefonSecureChannel(pipe.input, pipe.output, ByteArray(16), ByteArray(32) { 1 }, ByteArray(4) { 4 },
                        ByteArray(32) { 2 }, ByteArray(4) { 5 }).use { parent ->
                        val dispatch = DesktopScreenDraftNotesDispatch()
                        val original = dispatch.bind(DesktopScreenDraftNotesDispatch.Original("desktop", "paired-key",
                            "Paired desktop", parent, pipe, {}))
                        val foreign = DesktopScreenDraftNotesDispatch.Original("desktop", "paired-key", "Paired desktop",
                            parent, pipe, {})
                        assertFalse(dispatch.receive(original, kotlinx.serialization.json.JsonObject(emptyMap())))
                        assertSame(original, dispatch.candidate("desktop", "paired-key"))
                        dispatch.begin(f.activity, original, 2, 10_000).use { attempt ->
                            val offer = parent.receive()
                            assertFalse(dispatch.receive(foreign, offer))
                            assertTrue(dispatch.receive(original, offer))
                            val dialog = awaitValue {
                                shadowOf(Looper.getMainLooper()).idleFor(30, TimeUnit.MILLISECONDS)
                                ShadowDialog.getLatestDialog()?.takeIf { it.isShowing }
                            }
                            val image = views(dialog.window!!.decorView).filterIsInstance<ImageView>()
                                .single { it.contentDescription == f.activity.getString(R.string.desktop_screen_view_picture) }
                            assertNull(image.drawable)
                            f.button(dialog, R.string.desktop_screen_view_accept).performClick()
                            assertTrue(dispatch.receive(original, parent.receive())) // SEND
                            val drawn = awaitValue {
                                shadowOf(Looper.getMainLooper()).idleFor(30, TimeUnit.MILLISECONDS)
                                (image.drawable as? BitmapDrawable)?.bitmap
                            }
                            val pixel = drawn.getPixel(28, 16)
                            assertTrue(kotlin.math.abs(Color.green(pixel) - 110) <= 4 && kotlin.math.abs(Color.blue(pixel) - 228) <= 4)
                            f.controller.pause()
                            assertNull(image.drawable)
                            assertFalse(dialog.isShowing)
                            awaitValue { true.takeIf { attempt.drained } }
                            assertFalse(dispatch.receive(original, offer))
                            dispatch.retire(parent)
                            assertFalse(dispatch.receive(original, offer))
                            parent.send(kotlinx.serialization.json.JsonObject(mapOf("type" to kotlinx.serialization.json.JsonPrimitive("ping"))))
                            assertEquals(kotlinx.serialization.json.JsonPrimitive("pong"), parent.receive()["type"])
                        }
                    }
                }
            }
            assertTrue(server.waitFor(3, TimeUnit.SECONDS))
            assertEquals(0, server.exitValue())
        } finally {
            if (server.isAlive) server.destroyForcibly().waitFor(2, TimeUnit.SECONDS)
            readers.shutdownNow()
        }
    }

    companion object {
        private fun <T : Any> awaitValue(read: () -> T?): T {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2)
            while (System.nanoTime() - deadline < 0) {
                read()?.let { return it }
                Thread.sleep(5)
            }
            error("Timed out waiting for the original viewer")
        }

        private fun views(root: View): Sequence<View> = sequence {
            yield(root)
            if (root is ViewGroup) for (index in 0 until root.childCount) yieldAll(views(root.getChildAt(index)))
        }

        private fun jpeg(color: Int, width: Int = 57): ByteArray {
            val bitmap = Bitmap.createBitmap(width, 33, Bitmap.Config.ARGB_8888)
            try {
                bitmap.eraseColor(color)
                val output = ByteArrayOutputStream()
                assertTrue(bitmap.compress(Bitmap.CompressFormat.JPEG, 80, output))
                return output.toByteArray()
            } finally { bitmap.recycle() }
        }
    }
}
