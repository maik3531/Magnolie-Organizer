package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.pm.ServiceInfo
import android.os.SystemClock
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.ByteBuffer
import java.nio.channels.ServerSocketChannel
import java.nio.channels.SocketChannel
import java.time.Duration
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSystemClock

/** Joined actual permission/Service adapters + generated capture samples + real
 * dedicated sockets. Native default is Camera2/AudioRecord, not this test source.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneWebcamForegroundRunTest {
    private val secret get() = ByteArray(32) { it.toByte() }
    private class Source(val startAction: () -> Unit, val stopped: (Throwable?) -> Unit) : PhoneWebcamCaptureDevice {
        var closed = false
        override fun start() = startAction()
        override fun close() { if (!closed) { closed = true; stopped(null) } }
        override fun isCompletelyStopped() = closed
    }
    private class Fixture : AutoCloseable {
        val ui = PhoneWebcamPermissionHostTest.Fixture()
        val permit = ui.permit()
        val controller = Robolectric.buildService(PhoneWebcamPermissionHostTest.CaptureService::class.java).create()
        val service = controller.get()
        val prepared = CountDownLatch(1)
        val ended = CountDownLatch(1)
        var control = true
        var agreement = false
        var source: Source? = null
        var run: PhoneWebcamForegroundRun? = null
        init {
            ShadowSystemClock.advanceBy(Duration.ofMillis(100))
            service.getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel("webcam-run-test", "Synthetic run test", NotificationManager.IMPORTANCE_LOW))
            service.startForeground(920, Notification.Builder(service, "webcam-run-test").setSmallIcon(android.R.drawable.ic_menu_camera).build(),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        }
        fun create(peer: String = "127.0.0.1", native: Boolean = false): PhoneWebcamForegroundRun {
            val original = { check(control) { "original control revoked" } }
            val data = { check(agreement) { "actual receive agreement missing" } }
            val key = ByteArray(32) { it.toByte() }
            run = if (native) PhoneWebcamForegroundRun(permit, key, InetAddress.getByName(peer), original, data,
                { prepared.countDown() }, { ended.countDown() })
            else PhoneWebcamForegroundRun(permit, key, InetAddress.getByName(peer), original, data,
                { prepared.countDown() }, { ended.countDown() }) { actual, permission, sample, end ->
                Source({
                    permission.enterForeground(actual)
                    val time = SystemClock.elapsedRealtimeNanos()
                    sample(true, time, ByteArray(460800) { 75 })
                    sample(false, time, ByteArray(1920) { 42 })
                }, end).also { source = it }
            }
            return checkNotNull(run)
        }
        override fun close() {
            run?.close()
            if (run != null) assertTrue(ended.await(3, TimeUnit.SECONDS))
            service.stopForeground(Service.STOP_FOREGROUND_REMOVE)
            controller.destroy(); ui.close()
        }
    }
    private fun readPacket(channel: SocketChannel): ByteArray {
        val head = ByteBuffer.allocate(12)
        while (head.hasRemaining()) check(channel.read(head) > 0)
        val length = ByteBuffer.wrap(head.array()).int
        check(length in 34..460834)
        val body = ByteBuffer.allocate(length)
        while (body.hasRemaining()) check(channel.read(body) > 0)
        return head.array() + body.array()
    }

    @Test fun joinedForegroundCaptureFeedsActualDedicatedChannelOnlyAfterOriginalDataAgreement() {
        Fixture().use { f ->
            val run = f.create(); run.start(f.service)
            assertTrue(f.prepared.await(1, TimeUnit.SECONDS))
            ServerSocketChannel.open().use { listener ->
                listener.bind(InetSocketAddress("127.0.0.1", 0))
                SocketChannel.open(listener.localAddress).use { outgoing ->
                    listener.accept().use { incoming ->
                        f.agreement = true; run.startSending(outgoing)
                        PhoneWebcamMediaCodec(run.session, secret) {}.use { reference ->
                            assertArrayEquals(reference.encode(false, 0, 0, ByteArray(1920) { 42 }), readPacket(incoming))
                            assertArrayEquals(reference.encode(true, 0, 0, ByteArray(460800) { 75 }), readPacket(incoming))
                        }
                        run.close(); assertTrue(f.ended.await(2, TimeUnit.SECONDS))
                        assertTrue(run.isCompletelyStopped()); assertTrue(f.source!!.closed)
                        assertFalse(outgoing.isOpen)
                    }
                }
            }
        }
    }

    @Test fun wrongOriginalPeerAddressClosesOnlyOfferedChannelAndRetiresCaptureWithoutFallback() {
        Fixture().use { f ->
            val run = f.create(peer = "192.0.2.7"); run.start(f.service); f.agreement = true
            ServerSocketChannel.open().use { listener ->
                listener.bind(InetSocketAddress("127.0.0.1", 0))
                SocketChannel.open(listener.localAddress).use { outgoing ->
                    listener.accept().use {
                        val error = assertThrows(IllegalStateException::class.java) { run.startSending(outgoing) }
                        assertEquals("webcam_original_peer_address_required", error.message)
                        assertFalse(outgoing.isOpen); assertTrue(f.ended.await(2, TimeUnit.SECONDS))
                        assertTrue(f.source!!.closed); assertTrue(run.isCompletelyStopped())
                    }
                }
            }
        }
    }

    @Test fun captureReadyIsNotActualBilateralReceivePermissionAndCannotKeepSourceAliveOnDenial() {
        Fixture().use { f ->
            val run = f.create(); run.start(f.service)
            ServerSocketChannel.open().use { listener ->
                listener.bind(InetSocketAddress("127.0.0.1", 0))
                SocketChannel.open(listener.localAddress).use { outgoing ->
                    listener.accept().use {
                        val error = assertThrows(IllegalStateException::class.java) { run.startSending(outgoing) }
                        assertEquals("actual receive agreement missing", error.message)
                        assertTrue(f.ended.await(2, TimeUnit.SECONDS)); assertFalse(outgoing.isOpen)
                        assertTrue(run.isCompletelyStopped()); assertTrue(f.source!!.closed)
                    }
                }
            }
        }
    }

    @Test fun defaultNativeFactoryActuallyInspectsCameraAndDrainsUnsupportedDeviceRatherThanFakeReady() {
        Fixture().use { f ->
            val run = f.create(native = true)
            val error = assertThrows(IllegalStateException::class.java) { run.start(f.service) }
            assertEquals("webcam_requested_camera_unavailable", error.message)
            assertTrue(f.ended.await(3, TimeUnit.SECONDS)); assertTrue(run.isCompletelyStopped())
            assertEquals(1L, f.prepared.count); assertTrue(f.service.cameraLookups > 0)
        }
    }

    @Test fun controlLossDuringNativeFactoryConstructionClosesUnstartedCaptureWithoutInventingPendingIo() {
        Fixture().use { f ->
            val run = PhoneWebcamForegroundRun(f.permit, secret, InetAddress.getByName("127.0.0.1"),
                { check(f.control) { "original control revoked" } }, { check(f.agreement) },
                { f.prepared.countDown() }, { f.ended.countDown() }) { service, permission, sample, stopped ->
                f.control = false
                PhoneWebcamAndroidCapture(service, permission, sample, stopped)
            }
            f.run = run
            val error = assertThrows(IllegalStateException::class.java) { run.start(f.service) }
            assertEquals("original control revoked", error.message)
            assertTrue(f.ended.await(2, TimeUnit.SECONDS)); assertTrue(run.isCompletelyStopped())
            assertEquals(0, f.service.cameraLookups); assertEquals(1L, f.prepared.count)
        }
    }
}
