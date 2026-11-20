package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Dialog
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.text.BidiFormatter
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import io.gitlab.maik3531.magnolienotes.R
import java.util.concurrent.atomic.AtomicBoolean

/** Unadvertised view-only draft. The native caller supplies one exact offer
 * and a thread-safe, nonblocking original-channel guard. Approval only admits
 * this visible viewer; the caller still owns proof, SEND and receiver drain. */
internal class DesktopScreenViewer(
    private val activity: ComponentActivity,
    peerName: String,
    private val mode: Int,
    private val width: Int,
    private val height: Int,
    private val setupDeadlineNanos: Long,
    private val originalCurrent: () -> Unit,
    private val approved: (DesktopScreenViewer) -> Unit,
    private val requestStop: () -> Unit,
) : DefaultLifecycleObserver, AutoCloseable {
    private val handler = Handler(Looper.getMainLooper())
    private val retired = AtomicBoolean(false)
    private val decoding = AtomicBoolean(false)
    private val gate = Any()
    private var shown = false
    private var registered = false
    private var dialog: Dialog? = null
    private var image: ImageView? = null
    private var pending: Bitmap? = null
    private val displayPeer = BidiFormatter.getInstance().unicodeWrap(peerName.filterNot {
        it.isISOControl() || Character.getType(it) == Character.FORMAT.toInt()
    }.trim().take(100))
    @Volatile private var accepted = false
    @Volatile var uiDrained = false
        private set

    init {
        require(mode in 1..2 && width in 16..1920 && height in 16..1920 && width * height <= 1920 * 1080)
        require(displayPeer.isNotBlank())
    }

    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == Intent.ACTION_SCREEN_OFF) close()
        }
    }
    private val tick = object : Runnable {
        override fun run() {
            if (!uiCurrent()) { close(); return }
            if (accepted) {
                val next = synchronized(gate) { pending.also { pending = null } }
                if (next != null) {
                    if (retired.get()) next.recycle() else image?.setImageBitmap(next)
                }
            }
            handler.postDelayed(this, 50)
        }
    }

    fun show() {
        mainThread()
        check(!shown && !retired.get())
        shown = true
        try {
            check(uiCurrent(requireDialog = false)) { "desktop_screen_visible_host_required" }
            activity.lifecycle.addObserver(this)
            ContextCompat.registerReceiver(activity, screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
            registered = true
            val window = Dialog(activity).also { dialog = it }
            window.setTitle(if (mode == 1) R.string.desktop_screen_view_title else R.string.desktop_screen_extend_title)
            window.setCanceledOnTouchOutside(false)
            window.setOnDismissListener { close() }
            window.window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
            val layout = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL }
            val message = TextView(activity).apply {
                text = activity.getString(if (mode == 1) R.string.desktop_screen_view_prompt else R.string.desktop_screen_extend_prompt,
                    displayPeer)
            }
            val display = ImageView(activity).apply {
                scaleType = ImageView.ScaleType.FIT_CENTER
                contentDescription = activity.getString(R.string.desktop_screen_view_picture)
                visibility = View.GONE
            }
            image = display
            val accept = Button(activity).apply { setText(R.string.desktop_screen_view_accept) }
            val stop = Button(activity).apply {
                setText(R.string.abbrechen)
                setOnClickListener { close() }
            }
            accept.setOnClickListener {
                if (accepted || retired.get()) return@setOnClickListener
                if (!uiCurrent()) { close(); return@setOnClickListener }
                accepted = true
                accept.visibility = View.GONE
                message.visibility = View.GONE
                display.visibility = View.VISIBLE
                stop.setText(R.string.desktop_screen_view_stop)
                try { requireViewing(); approved(this) } catch (_: Exception) { close() }
            }
            layout.addView(message)
            layout.addView(display, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
            layout.addView(accept)
            layout.addView(stop)
            window.setContentView(layout)
            window.show()
            window.window?.setLayout(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT)
            handler.post(tick)
        } catch (failure: Exception) {
            close()
            throw failure
        }
    }

    /** Safe for the exact receiver worker. No Activity or View reads off main. */
    fun requireViewing() {
        check(accepted && !retired.get()) { "desktop_screen_viewer_not_approved" }
        originalCurrent()
        check(!retired.get()) { "desktop_screen_viewer_retired" }
    }

    /** Transfers one unique JPEG buffer from the authenticated receiver.
     * Empty heartbeats never touch the image slot. */
    fun offer(jpeg: ByteArray) {
        if (!decoding.compareAndSet(false, true)) {
            jpeg.fill(0)
            close()
            error("desktop_screen_original_decoder_busy")
        }
        var decoded: Bitmap? = null
        try {
            requireViewing()
            if (jpeg.isEmpty()) return
            requireDesktopScreenJpeg(jpeg, width, height)
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true; inScaled = false }
            BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, bounds)
            check(bounds.outWidth == width && bounds.outHeight == height && bounds.outMimeType == "image/jpeg")
            requireViewing()
            val options = BitmapFactory.Options().apply { inPreferredConfig = Bitmap.Config.ARGB_8888; inScaled = false }
            decoded = checkNotNull(BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, options))
            check(decoded.width == width && decoded.height == height && decoded.byteCount <= width * height * 4)
            requireViewing()
            synchronized(gate) {
                check(!retired.get())
                pending?.recycle() // Only undisplayed bitmaps may be recycled here.
                pending = decoded
                decoded = null
            }
        } catch (failure: Exception) {
            close()
            throw failure
        } finally {
            decoded?.recycle()
            jpeg.fill(0)
            decoding.set(false)
        }
    }

    private fun uiCurrent(requireDialog: Boolean = true): Boolean = try {
        check(!retired.get() && !activity.isFinishing && !activity.isDestroyed &&
            activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) &&
            activity.window.decorView.windowVisibility == View.VISIBLE)
        check(activity.getSystemService(PowerManager::class.java)?.isInteractive == true)
        val keyguard = checkNotNull(activity.getSystemService(KeyguardManager::class.java))
        check(!keyguard.isDeviceLocked && !keyguard.isKeyguardLocked)
        if (requireDialog) check(dialog?.isShowing == true)
        if (!accepted) check(System.nanoTime() - setupDeadlineNanos < 0)
        originalCurrent()
        !retired.get()
    } catch (_: Exception) { false }

    override fun onPause(owner: LifecycleOwner) = close()
    override fun onDestroy(owner: LifecycleOwner) = close()

    override fun close() {
        synchronized(gate) {
            if (!retired.compareAndSet(false, true)) return
            pending?.recycle()
            pending = null
        }
        if (Looper.myLooper() == Looper.getMainLooper()) closeUi() else handler.post { closeUi() }
    }

    private fun closeUi() {
        try {
            handler.removeCallbacks(tick)
            image?.setImageDrawable(null)
            image = null
            dialog?.let { it.setOnDismissListener(null); it.dismiss() }
            dialog = null
        } finally {
            activity.lifecycle.removeObserver(this)
            try {
                if (registered) { registered = false; activity.unregisterReceiver(screenOff) }
            } finally {
                requestStop() // Signal only; the caller must not wait on the UI thread.
            }
        }
        uiDrained = true
    }

    private fun mainThread() = check(Looper.myLooper() == Looper.getMainLooper())
}
