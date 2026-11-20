package io.gitlab.maik3531.magnolienotes.telefon

import android.app.KeyguardManager
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.view.View
import androidx.activity.ComponentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Native draft composition, not dispatched or advertised by Notes. Begin only
 * from an explicit action on the original Activity. Hold one slot until drained.
 * Only the original authenticated reader supplies frames to receive(). */
internal class DesktopScreenDraftPhoneAttempt(
    private val activity: ComponentActivity,
    private val peerName: String,
    private val parent: TelefonSecureChannel,
    originalPipe: TelefonTcpRoehre,
    requireOriginalParent: () -> Unit,
    private val mode: Int,
    budgetMs: Long,
) : DefaultLifecycleObserver, AutoCloseable {
    private val handler = Handler(Looper.getMainLooper())
    private val wire = DesktopScreenDraftPhoneChannel(parent, originalPipe, requireOriginalParent)
    private val request = DesktopScreenDraftPhoneRequest(wire, mode, budgetMs)
    private val stopping = AtomicBoolean(false)
    private val signal = CountDownLatch(1)
    @Volatile private var began = false
    @Volatile private var uiDrained = false
    @Volatile private var viewer: DesktopScreenReceiveAttempt? = null // Assigned on main.
    private val writer = Thread(::writeControls, "magnolie-desktop-screen-control").apply { isDaemon = true }

    fun begin() {
        check(Looper.myLooper() == Looper.getMainLooper() && !began && !stopping.get())
        try {
            requireVisible()
            request.requireCurrent()
            activity.lifecycle.addObserver(this)
            began = true
            writer.start()
            handler.post(tick)
        } catch (failure: Exception) { close(); throw failure }
    }

    private fun requireVisible() {
        check(!activity.isDestroyed && !activity.isFinishing &&
            activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) &&
            activity.window.decorView.windowVisibility == View.VISIBLE &&
            activity.getSystemService(PowerManager::class.java)?.isInteractive == true)
        val lock = checkNotNull(activity.getSystemService(KeyguardManager::class.java))
        check(!lock.isDeviceLocked && !lock.isKeyguardLocked)
    }

    private fun writeControls() {
        try {
            request.writeRequest()
            signal.await()
        } catch (_: Exception) {
            close()
        } finally {
            // Terminal only. A retired viewer cannot publish PREPARED or SEND.
            runCatching { request.writeStop() }
        }
    }

    fun receive(actual: TelefonSecureChannel, frame: JsonObject): Boolean {
        if (!began || stopping.get() || actual !== parent) return false
        return try {
            request.receive(actual, frame).also { accepted ->
                if (accepted && (frame["body"] as JsonObject)["op"] == JsonPrimitive("stop")) close()
            }
        } catch (_: Exception) {
            close()
            false
        }
    }

    private val tick = object : Runnable {
        override fun run() {
            if (!stopping.get()) {
                try {
                    requireVisible()
                    request.requireCurrent()
                    request.takeOffer()?.let(::showOffer)
                    request.takeSend()?.let { receipt ->
                        try { check(viewer?.acceptSend(parent, receipt) == true) }
                        finally { receipt.fill(0) }
                    }
                    if (viewer?.drained == true) close()
                } catch (_: Exception) { close() }
            }
            if (!stopping.get()) handler.postDelayed(this, 25)
        }
    }

    private fun showOffer(offer: JsonObject) {
        fun field(key: String) = (offer.getValue(key) as JsonPrimitive).content
        fun hex(key: String) = field(key).chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        check(viewer == null)
        val secret = hex("secret")
        val port = field("port").toInt()
        val original = try {
            DesktopScreenReceiveAttempt(activity, peerName, parent, hex("session"), secret, mode,
                field("width").toInt(), field("height").toInt(), request.setupDeadlineNanos, request::requireCurrent,
                { guard -> wire.openOriginalData(port, guard) }, request::writePrepared)
        } finally { secret.fill(0) }
        viewer = original
        original.show()
    }

    override fun onPause(owner: LifecycleOwner) = close()
    override fun onDestroy(owner: LifecycleOwner) = close()

    override fun close() {
        if (!stopping.compareAndSet(false, true)) return
        request.close()
        signal.countDown()
        if (Looper.myLooper() == Looper.getMainLooper()) finishUi() else handler.post { finishUi() }
    }

    private fun finishUi() {
        handler.removeCallbacks(tick)
        activity.lifecycle.removeObserver(this)
        viewer?.close()
        uiDrained = true
    }

    val drained: Boolean get() = uiDrained && viewer?.drained != false && !writer.isAlive
}
