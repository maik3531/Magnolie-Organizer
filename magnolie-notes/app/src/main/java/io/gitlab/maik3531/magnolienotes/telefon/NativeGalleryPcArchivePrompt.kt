package io.gitlab.maik3531.magnolienotes.telefon

import android.app.AlertDialog
import android.os.Handler
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import io.gitlab.maik3531.magnolienotes.R
import java.util.concurrent.atomic.AtomicBoolean

/** A real local foreground choice only. It never reads a provider, authorizes
 * replacement or restarts the original selection's admission clock. */
internal object NativeGalleryPcArchivePrompt {
    internal fun request(activity: ComponentActivity, selection: NativeGalleryPcArchiveSelection,
        result: (Result<Int>) -> Unit): AutoCloseable {
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
        val delivered = AtomicBoolean(false)
        var dialog: AlertDialog? = null
        var chosen = -1
        fun finish(outcome: Result<Int>) {
            if (!delivered.compareAndSet(false, true)) return
            if (outcome.isFailure) selection.close()
            result(outcome)
        }
        fun cancel() = finish(Result.failure(PhotoFolderScopeError("gallery_archive_local_confirmation_canceled")))
        fun foreground() {
            if (activity.isFinishing || activity.isDestroyed || !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
                DeviceFileControl.fail("gallery_archive_foreground_required")
        }
        val observer = object : DefaultLifecycleObserver {
            override fun onPause(owner: LifecycleOwner) { selection.close(); dialog?.cancel(); cancel() }
            override fun onDestroy(owner: LifecycleOwner) { selection.close(); dialog?.cancel(); cancel() }
        }
        try {
            foreground()
            if (selection.choices.isEmpty()) DeviceFileControl.fail("gallery_archive_no_published_pc_rows")
            activity.lifecycle.addObserver(observer)
            val prompt = AlertDialog.Builder(activity).setTitle(R.string.medien_pc_archiv_titel)
                .setSingleChoiceItems(selection.choices.map { it.name }.toTypedArray(), -1) { _, index ->
                    chosen = index; dialog?.getButton(AlertDialog.BUTTON_POSITIVE)?.isEnabled = true
                }
                .setPositiveButton(R.string.medien_pc_archiv_kopie) { _, _ ->
                    try {
                        foreground()
                        if (chosen !in selection.choices.indices) DeviceFileControl.fail("gallery_archive_original_selection_required")
                        finish(Result.success(chosen))
                    } catch (error: Exception) { finish(Result.failure(error)) }
                }.setNegativeButton(android.R.string.cancel) { _, _ -> cancel() }.create()
            dialog = prompt
            prompt.setOnCancelListener { cancel() }
            prompt.setOnDismissListener { if (!delivered.get()) cancel() }
            prompt.show(); prompt.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled = false
        } catch (error: Exception) { finish(Result.failure(error)) }
        return AutoCloseable {
            fun close() {
                activity.lifecycle.removeObserver(observer)
                if (!delivered.get()) cancel()
                dialog?.dismiss()
            }
            if (Looper.myLooper() == Looper.getMainLooper()) close() else Handler(Looper.getMainLooper()).post { close() }
        }
    }
}
