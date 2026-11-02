package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Handler
import android.os.Looper
import java.util.concurrent.atomic.AtomicBoolean

/** Native transport ownership, retained until actual UI cleanup. No worker-END
 * or quota receipt is implied by closing the control plane.
 */
internal class NativeGalleryFileConnection internal constructor(internal val channel: TelefonSecureChannel,
    private val released: (NativeGalleryFileConnection) -> Unit) : AutoCloseable {
    private val ended = AtomicBoolean(false)
    private val permissionQueued = AtomicBoolean(false)
    @Volatile private var bound: NativeGalleryFileRuntime? = null
    val runtime: NativeGalleryFileRuntime get() = bound?.takeUnless { ended.get() }
        ?: DeviceFileControl.fail("gallery_file_connection_ended")
    internal val isEnded get() = ended.get()

    internal fun bind(value: NativeGalleryFileRuntime) {
        check(Looper.myLooper() == Looper.getMainLooper())
        check(bound == null)
        bound = value
        if (ended.get()) { close(); DeviceFileControl.fail("gallery_file_connection_ended") }
    }

    /** Called after native I/O actually ends, outside the TelefonWerk monitor. */
    internal fun transportEnded() {
        ended.set(true)
        bound?.revokeControl()
        if (Looper.myLooper() == Looper.getMainLooper()) close()
        else Handler(Looper.getMainLooper()).post { close() }
    }

    internal fun enqueuePermissionCommand(operation: (NativeGalleryFileRuntime) -> Unit) {
        if (ended.get() || !permissionQueued.compareAndSet(false, true)) DeviceFileControl.fail("gallery_permission_command_busy")
        val posted = Handler(Looper.getMainLooper()).post {
            try { operation(runtime) }
            catch (_: Exception) {
                // Fail closed on the file route, not by crashing the UI or
                // inventing delivery. A caller receives no success reply.
                runCatching { close() }
            } finally { permissionQueued.set(false) }
        }
        if (!posted) { permissionQueued.set(false); DeviceFileControl.fail("gallery_permission_foreground_required") }
    }

    override fun close() {
        ended.set(true)
        bound?.revokeControl()
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
        bound?.close()
        bound = null
        released(this)
    }
}
