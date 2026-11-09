package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.launch
import java.lang.ref.WeakReference

/** Passive foreground registration only. No store, permission or transport is
 * opened by registering MainActivity. Only its existing authenticated connection
 * can dispatch an offer into this Activity-owned action. */
internal object NativeGalleryPcReplacementForeground {
    private var activity = WeakReference<ComponentActivity>(null)
    private var host = WeakReference<NativeGalleryPcWriteConsentHost>(null)
    internal fun register(owner: ComponentActivity, consent: NativeGalleryPcWriteConsentHost) {
        check(Looper.myLooper() == Looper.getMainLooper())
        activity = WeakReference(owner); host = WeakReference(consent)
        owner.lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onDestroy(source: LifecycleOwner) {
                if (activity.get() === owner) { activity.clear(); host.clear() }
                owner.lifecycle.removeObserver(this)
            }
        })
    }
    internal fun request(connection: NativeGalleryFileConnection,
        action: suspend (ComponentActivity, NativeGalleryPcWriteConsentHost) -> Unit): kotlinx.coroutines.Job {
        check(Looper.myLooper() == Looper.getMainLooper())
        val current = activity.get()?.takeIf { it.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) }
            ?: DeviceFileControl.fail("gallery_pc_write_foreground_required")
        val consent = host.get() ?: DeviceFileControl.fail("gallery_pc_write_foreground_required")
        val job = current.lifecycleScope.launch(start = CoroutineStart.LAZY) {
            try { action(current, consent) }
            catch (canceled: CancellationException) { throw canceled }
            catch (_: Exception) {
                android.widget.Toast.makeText(current, io.gitlab.maik3531.magnolienotes.R.string.fehler_allgemein,
                    android.widget.Toast.LENGTH_LONG).show()
            }
        }
        connection.installPcUiJob(job); job.start(); return job
    }
}
