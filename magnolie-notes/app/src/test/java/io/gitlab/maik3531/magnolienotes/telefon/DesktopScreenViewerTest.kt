package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.app.Dialog
import android.app.KeyguardManager
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
import io.gitlab.maik3531.magnolienotes.R
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.channels.ServerSocketChannel
import java.nio.channels.SocketChannel
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.*
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
