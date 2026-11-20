package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.Entwicklermodus
import io.gitlab.maik3531.magnolienotes.Entwicklermodus.Medienphase

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.annotation.RequiresApi
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.SecureRandom
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/** The original authenticated Notes WLAN request. Only a current visible host
 * can answer the desktop offer. The caller must route only v26 messages from
 * the regular authenticated reader and retain this owner until drain. */
@RequiresApi(29)
internal class PhoneScreenNotesRun(private val context: Context, private val parent: TelefonSecureChannel,
    private val pipe: TelefonTcpRoehre, private val requireParent: () -> Unit,
    private val host: () -> PhoneScreenConsentHost?, track: (String) -> Unit = {}) : AutoCloseable {
    private val ui = Handler(Looper.getMainLooper())
    private val stopped = AtomicBoolean(false)
    private val issued = SystemClock.elapsedRealtime()
    private val wire = PhoneScreenNotesChannel(parent, pipe, requireParent, track)
    private val probe = JsonObject(mapOf("version" to JsonPrimitive(PhoneScreenControl.VERSION), "op" to JsonPrimitive("probe"),
        "request_id" to JsonPrimitive(UUID.randomUUID().toString()),
        "nonce" to JsonPrimitive(ByteArray(32).also { SecureRandom().nextBytes(it) }.toHex())))
    private val control = PhoneScreenNotesControl(parent, probe, ::current)
    private val probeWritten = AtomicBoolean(false)
    private val probeWorker = Thread(::writeProbe, "magnolie-screen-probe")
    @Volatile private var request: PhoneScreenViewRequest? = null
    @Volatile private var capture: PhoneScreenCaptureHandle? = null
    @Volatile private var pending: PhoneScreenFrameSlot? = null
    @Volatile private var sender: PhoneScreenSendRun? = null
    @Volatile private var connector: Thread? = null
    @Volatile private var terminalWorker: Thread? = null
    @Volatile private var terminalBody: JsonObject? = null
    @Volatile private var uiStopped = false
    @Volatile var failure: Exception? = null
        private set
    private val setupDeadline = Runnable {
        if (!stopped.get()) {
            try {
                if (!control.hasOriginalSend()) fail(IllegalStateException("screen_original_probe_expired"), "retired")
            } catch (error: Exception) { fail(error, "retired") }
        }
    }

    fun start() {
        current()
        probeWorker.start()
        ui.postDelayed(setupDeadline, (60_000L - (SystemClock.elapsedRealtime() - issued)).coerceAtLeast(0))
    }

    private fun writeProbe() {
        try {
            // The reader may see the reply while the protected writer is still
            // returning. Its guard still prohibits a write after retirement.
            wire.write(probe) { current(); probeWritten.set(true) }
        } catch (error: Exception) { fail(error) }
    }

    private fun current() {
        check(!stopped.get()) { "screen_notes_run_retired" }
        requireParent()
        pipe.pruefen()
        check(!stopped.get()) { "screen_notes_run_retired" }
    }

    fun receive(actual: TelefonSecureChannel, message: JsonObject): Boolean {
        val body = wire.bodyFrom(actual, message)
        if (!probeWritten.get()) return false
        return if (body.string("op") == "offer") {
            if (!control.acceptOffer(actual, body)) false
            else {
                terminalBody = JsonObject(body.filterKeys { it == "version" || it == "request_id" || it == "nonce" || it == "session" })
                ui.post { requestConsent(body) }
            }
        } else {
            if (!control.receive(actual, body)) false
            else {
                if (body.string("op") != "send") stop(remote = true)
                else Entwicklermodus(context).medienEreignis(Medienphase.SPIEGELUNG_SEND_BESTAETIGT)
                true
            }
        }
    }

    private fun requestConsent(offer: JsonObject) {
        try {
            current()
            check(SystemClock.elapsedRealtime() - issued in 0L until 60_000L) { "screen_original_probe_expired" }
            val original = PhoneScreenViewRequest(::current)
            request = original
            checkNotNull(host()) { "screen_visible_activity_required" }.request(original) { result ->
                val consent = result.getOrElse {
                    fail(it as? Exception ?: IllegalStateException("screen_consent_failed", it), "permission_denied")
                    return@request
                }
                try {
                    current()
                    val width = offer.long("width").toInt()
                    val height = offer.long("height").toInt()
                    val slot = PhoneScreenFrameSlot(width, height)
                    pending = slot
                    val handle = PhoneScreenServiceStarts.startJpeg(context, original, consent, width, height,
                        offer.long("density").toInt(), slot)
                    capture = handle
                    val worker = Thread({ connect(offer, handle, slot) }, "magnolie-screen-connect")
                    connector = worker
                    worker.start()
                } catch (error: Exception) {
                    consent.close()
                    fail(error)
                }
            }
        } catch (error: Exception) { fail(error) }
    }

    private fun connect(offer: JsonObject, handle: PhoneScreenCaptureHandle, slot: PhoneScreenFrameSlot) {
        try {
            val until = System.nanoTime() + 8_000_000_000L
            while (!handle.isActive) {
                current()
                check(System.nanoTime() - until < 0) { "screen_capture_start_timeout" }
                Thread.sleep(20)
            }
            val nativeGuard = { current(); handle.requireActive() }
            control.prepared(nativeGuard, wire::write)
            val socket = openPhoneScreenWlanSocket(pipe, offer.long("port").toInt(), nativeGuard)
            try {
                nativeGuard()
                val session = offer.string("session").fromHex()
                val secret = offer.string("secret").fromHex()
                val run = try { PhoneScreenSendRun(socket, session, secret, offer.long("width").toInt(),
                    offer.long("height").toInt(), slot, nativeGuard, control::hasOriginalSend) }
                finally { secret.fill(0) }
                sender = run
                try {
                    nativeGuard()
                    run.start()
                    while (!run.isDrained()) {
                        current()
                        handle.requireActive()
                        run.failure?.let { throw it }
                        Thread.sleep(20)
                    }
                    run.failure?.let { throw it }
                } finally {
                    run.close()
                }
            } finally { socket.close() }
        } catch (error: Exception) { if (!stopped.get()) fail(error) }
        finally { close() }
    }

    private fun fail(error: Exception, reason: String = "capture_failed") {
        if (!stopped.get() && failure == null) {
            failure = error
            Entwicklermodus(context).medienEreignis(Medienphase.SPIEGELUNG_FEHLER)
        }
        stop(reason = reason)
    }

    override fun close() = stop()

    private fun stop(remote: Boolean = false, reason: String? = null) {
        if (!stopped.compareAndSet(false, true)) return
        ui.removeCallbacks(setupDeadline)
        control.close()
        request?.close()
        pending?.close()
        sender?.close()
        if (!remote) terminalBody?.let { original ->
            val body = if (reason == null) JsonObject(original + ("op" to JsonPrimitive("stop")))
            else JsonObject(original + mapOf("op" to JsonPrimitive("error"), "reason" to JsonPrimitive(reason)))
            val worker = Thread({
                // Terminal only, no capture authority, same bounded parent. A
                // vanished parent already stops the other side independently.
                runCatching { wire.write(body) }
            }, "magnolie-screen-terminal")
            terminalWorker = worker
            runCatching { worker.start() }
        }
        ui.post {
            try { capture?.close() } finally { uiStopped = true }
        }
    }

    /** Called on the main looper, never joins Android/IO workers. */
    fun isDrained(): Boolean = uiStopped && !probeWorker.isAlive && connector?.isAlive != true && terminalWorker?.isAlive != true &&
        (sender?.isDrained() ?: true) && (capture?.isDrained() ?: true)

    private fun ByteArray.toHex() = joinToString("") { (it.toInt() and 255).toString(16).padStart(2, '0') }
    private fun String.fromHex() = ByteArray(length / 2) { substring(it * 2, it * 2 + 2).toInt(16).toByte() }
}
