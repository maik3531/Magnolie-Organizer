package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Service
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.annotation.RequiresApi
import kotlinx.serialization.json.*
import java.net.InetSocketAddress
import java.nio.channels.SelectionKey
import java.nio.channels.Selector
import java.nio.channels.SocketChannel
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Actual original-parent → OS permission → FGS → dedicated binary lane join.
 * Only fresh authenticated desktop discovery may construct/start this runtime.
 * No saved opt-in, Activity launch, listener, parent replacement or retry.
 */
@RequiresApi(30)
internal class PhoneWebcamNotesRuntime(private val context: Context, private val parent: TelefonSecureChannel,
    private val pipe: TelefonTcpRoehre, private val nativeCurrent: () -> Unit,
    private val send: (JsonObject, () -> Unit) -> Unit,
    private val captureFactory: (Service, PhoneWebcamCapturePermit, (Boolean, Long, ByteArray) -> Unit, (Throwable?) -> Unit) -> PhoneWebcamCaptureDevice =
        { service, permission, sample, stopped -> PhoneWebcamAndroidCapture(service, permission, sample, stopped) }) : AutoCloseable {
    val token = Any()
    private val closed = AtomicBoolean(false)
    private val failing = AtomicBoolean(false)
    private val started = AtomicBoolean(false)
    private val sendStarted = AtomicBoolean(false)
    private val ui = Handler(Looper.getMainLooper())
    private val uiToken = Any()
    private val worker = ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS, ArrayBlockingQueue(4),
        { task -> Thread(task, "Magnolie original webcam control") })
    private val exchange = PhoneWebcamControlExchange(parent, ::current)
    @Volatile private var probe: JsonObject? = null
    @Volatile private var request: PhoneWebcamCaptureRequest? = null
    @Volatile private var run: PhoneWebcamForegroundRun? = null
    @Volatile private var socket: SocketChannel? = null
    @Volatile var terminalFailure: Throwable? = null
        private set

    private fun parentCurrent() {
        nativeCurrent()
        check(!pipe.isClosed) { "webcam_original_parent_retired" }
    }
    private fun current() {
        parentCurrent()
        check(!closed.get() && !failing.get()) { "webcam_original_control_retired" }
    }
    fun start() {
        check(started.compareAndSet(false, true)) { "webcam_control_probe_already_used" }
        ui.postAtTime({
            if (!sendStarted.get()) fail(java.util.concurrent.TimeoutException("webcam_original_start_timeout"), "retired")
        }, uiToken, SystemClock.uptimeMillis() + PhoneWebcamControl.MAX_TTL_MS)
        enqueue {
            val body = exchange.probe(parent)
            probe = body
            sendBody(body)
        }
    }

    /** Foreign/late packets are rejected BEFORE this owner's worker queue. */
    fun receive(message: JsonObject): Boolean {
        val body = PhoneWebcamControl.validateMessage(message)
        val original = probe ?: return false
        if (message.string("kind") != PhoneWebcamControl.REPORT || body["request_id"] != original["request_id"] ||
            body["nonce"] != original["nonce"]) return false
        if (body.string("op") !in setOf("offer", "unavailable") && body["session"] != request?.session?.let(::JsonPrimitive)) return false
        current()
        enqueue { receiveOriginal(message) }
        return true
    }

    private fun receiveOriginal(message: JsonObject) {
        when ((message["body"] as JsonObject).string("op")) {
            "offer", "unavailable" -> {
                val original = exchange.acceptOffer(parent, message)
                if (original == null) { close(); return }
                request = original
                ui.postAtTime({
                    try {
                        current()
                        PhoneWebcamForeground.request(original) { result ->
                            result.fold({ permit ->
                                try {
                                    current()
                                    val capture = exchange.createRun(parent, permit, pipe.remoteAddress,
                                        { body -> enqueue { connectAndPrepare(body) } },
                                        { error -> if (error != null) fail(error, "capture_failed") else close() }, captureFactory)
                                    run = capture
                                    current()
                                    PhoneWebcamServiceStarts.start(context, capture)
                                } catch (error: Exception) { permit.close(); fail(error, "capture_failed") }
                            }, { error -> fail(error, "permission_denied") })
                        }
                    } catch (error: Exception) { original.close(); fail(error, "foreground_required") }
                }, uiToken, SystemClock.uptimeMillis())
            }
            "send" -> {
                exchange.acceptSend(parent, message)
                checkNotNull(run).startSending(checkNotNull(socket) { "webcam_original_media_channel_required" })
                sendStarted.set(true)
            }
            "stop", "error" -> { exchange.acceptStop(parent, message); close() }
            else -> error("webcam_control_unexpected_report")
        }
    }

    private fun connectAndPrepare(body: JsonObject) {
        current()
        check(socket == null) { "webcam_original_media_channel_already_used" }
        val channel = SocketChannel.open()
        socket = channel
        try {
            current()
            channel.configureBlocking(false)
            channel.bind(InetSocketAddress(pipe.localAddress, 0))
            val deadline = System.nanoTime() + 2_000_000_000L
            Selector.open().use { selector ->
                channel.register(selector, SelectionKey.OP_CONNECT)
                channel.connect(InetSocketAddress(pipe.remoteAddress, checkNotNull(exchange.port)))
                while (!channel.finishConnect()) {
                    current()
                    check(System.nanoTime() < deadline) { "webcam_original_media_connect_timeout" }
                    selector.select(50); selector.selectedKeys().clear()
                }
            }
            current()
            sendBody(body)
        } catch (error: Throwable) { channel.close(); throw error }
    }

    private fun sendBody(body: JsonObject) {
        current()
        PhoneWebcamControl.validateBody(body, PhoneWebcamControl.REQUEST)
        send(TelefonNachrichten.message(PhoneWebcamControl.REQUEST, body, PhoneWebcamControl.MAX_TTL_MS), ::current)
    }
    private fun enqueue(action: () -> Unit) {
        if (closed.get() || failing.get()) return
        try { worker.execute {
            try { current(); action() }
            catch (error: Exception) { fail(error, "capture_failed") }
        } } catch (error: Exception) { terminalFailure = error; close() }
    }
    private fun fail(error: Throwable, reason: String) {
        if (closed.get() || !failing.compareAndSet(false, true)) return
        terminalFailure = error
        exchange.close() // Stop capture immediately, not after a control-writer wait.
        runCatching { socket?.close() }
        ui.removeCallbacksAndMessages(uiToken)
        val original = probe
        val session = request?.session
        try { worker.execute {
            try {
                if (original != null && session != null) {
                    val body = JsonObject(original + mapOf("op" to JsonPrimitive("error"), "session" to JsonPrimitive(session), "reason" to JsonPrimitive(reason)))
                    PhoneWebcamControl.validateBody(body, PhoneWebcamControl.REQUEST)
                    send(TelefonNachrichten.message(PhoneWebcamControl.REQUEST, body, PhoneWebcamControl.MAX_TTL_MS), ::parentCurrent)
                }
            } catch (_: Exception) { /* Lost original parent: no foreign/reconnect send. */ }
            finally { close() }
        } } catch (_: Exception) { close() }
    }
    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        exchange.close(); request?.close()
        runCatching { socket?.close() }
        ui.removeCallbacksAndMessages(uiToken)
        worker.shutdownNow()
    }
    fun isCompletelyStopped() = closed.get() && worker.isTerminated && (run?.isCompletelyStopped() ?: true)
}
