package io.gitlab.maik3531.magnolienotes.telefon

import android.app.AlertDialog
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import java.util.concurrent.atomic.AtomicBoolean

/** Native document witness only. Neither Android permission nor archive/trash
 * authority; no backup/retention subsystem is constructed for receiving media. */
internal class NativeGalleryReceiveBookPermit private constructor(private val currentDocuments: () -> Ablage?,
    private val unlocked: () -> Boolean) {
    private val documents = currentDocuments() ?: fail()
    private val book = documents.bestand.value
    private val saved = documents.personalActorSavedBookState() ?: fail()
    private var revoked = false
    init { requireCurrent() }
    @Synchronized internal fun requireCurrent() {
        try {
            if (revoked || !unlocked() || currentDocuments() !== documents || documents.bestand.value !== book ||
                documents.personalActorSavedBookState() != saved) fail()
        } catch (error: Exception) { revoked = true; throw error }
    }
    internal fun requireArchiveBook(permit: NativeGalleryTrashBookPermit) {
        requireCurrent(); permit.requireOriginalBook(documents, saved); requireCurrent()
    }
    companion object {
        internal fun capture(currentDocuments: () -> Ablage?, unlocked: () -> Boolean) = NativeGalleryReceiveBookPermit(currentDocuments, unlocked)
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_receive_current_saved_book_required")
    }
}

/** Only a real local positive dialog button can approve this one-use selection.
 * A wire Boolean, source configure ticket, OS READ grant or archive restoration
 * session cannot construct it. It authorizes policy CAS, never row/file writes. */
internal class NativeGalleryReceiveConsent private constructor(private val activity: ComponentActivity,
    internal val mediaType: GalleryMediaType, internal val configurer: NativeFileReceiveConfigurer,
    private val book: NativeGalleryReceiveBookPermit) : DefaultLifecycleObserver, AutoCloseable {
    private val issued = DeviceFileControl.monotonicMs()
    private var last = issued
    private val revoked = AtomicBoolean(false)
    private val closed = AtomicBoolean(false)
    private val approved = AtomicBoolean(false)
    private val used = AtomicBoolean(false)
    init { alive(); activity.lifecycle.addObserver(this) }

    @Synchronized private fun alive() {
        val now = DeviceFileControl.monotonicMs()
        try {
            if (revoked.get() || closed.get() || now < last || now - issued >= DeviceFileControl.MAX_TTL_MS ||
                activity.isFinishing || activity.isDestroyed || !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
                DeviceFileControl.fail("gallery_receive_foreground_not_current")
            book.requireCurrent(); last = now
        } catch (error: Exception) { revoked.set(true); throw error }
    }
    private fun approve() { alive(); if (!approved.compareAndSet(false, true)) DeviceFileControl.fail("gallery_receive_consent_already_approved") }
    internal fun requireCurrent() {
        alive()
        if (!approved.get()) DeviceFileControl.fail("gallery_receive_local_confirmation_required")
    }
    internal fun requireConfigurer(current: NativeFileReceiveConfigurer?) {
        requireCurrent()
        if (current == null || current.owner !== configurer.owner || current.peerId != configurer.peerId ||
            current.identitySha256 != configurer.identitySha256 || current.permissionEpoch != configurer.permissionEpoch ||
            current.pairingEpoch != configurer.pairingEpoch) {
            revoked.set(true); DeviceFileControl.fail("gallery_receive_configurer_changed")
        }
    }
    internal fun consume() {
        requireCurrent()
        if (!used.compareAndSet(false, true)) DeviceFileControl.fail("gallery_receive_consent_already_used")
    }
    override fun onPause(owner: LifecycleOwner) { revoked.set(true) }
    override fun onDestroy(owner: LifecycleOwner) { close() }
    override fun close() {
        revoked.set(true)
        if (!closed.compareAndSet(false, true)) return
        if (Looper.myLooper() == Looper.getMainLooper()) activity.lifecycle.removeObserver(this)
        else Handler(Looper.getMainLooper()).post { activity.lifecycle.removeObserver(this) }
    }

    companion object {
        internal fun request(activity: ComponentActivity, nativePeerLabel: String, mediaType: GalleryMediaType,
            configurer: NativeFileReceiveConfigurer, book: NativeGalleryReceiveBookPermit,
            result: (Result<NativeGalleryReceiveConsent>) -> Unit): AutoCloseable {
            if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
            if (Build.VERSION.SDK_INT < 30) DeviceFileControl.fail("gallery_receive_android30_required")
            if (nativePeerLabel.isBlank() || nativePeerLabel.length > 160 || nativePeerLabel.any { it.code < 32 || it.code == 127 })
                DeviceFileControl.fail("gallery_receive_native_peer_label_required")
            val selection = NativeGalleryReceiveConsent(activity, mediaType, configurer, book)
            val delivered = AtomicBoolean(false)
            fun finish(outcome: Result<NativeGalleryReceiveConsent>) {
                if (!delivered.compareAndSet(false, true)) return
                if (outcome.isFailure) selection.close()
                try { result(outcome) } catch (_: Exception) { selection.close() }
            }
            fun canceled() = finish(Result.failure(PhotoFolderScopeError("gallery_receive_local_consent_canceled")))
            var dialog: AlertDialog? = null
            try {
                val title = activity.getString(if (mediaType == GalleryMediaType.IMAGES) R.string.medien_sync_fotos else R.string.medien_sync_videos)
                val prompt = AlertDialog.Builder(activity).setTitle(title + "\n" + nativePeerLabel)
                    .setMessage(R.string.medien_empfang_bestaetigen)
                    .setPositiveButton(android.R.string.ok) { _, _ ->
                        try { selection.approve(); finish(Result.success(selection)) }
                        catch (error: Exception) { finish(Result.failure(error)) }
                    }
                    .setNegativeButton(android.R.string.cancel) { _, _ -> canceled() }.create()
                dialog = prompt
                prompt.setOnCancelListener { canceled() }
                prompt.setOnDismissListener { if (!delivered.get()) canceled() }
                prompt.show()
            } catch (error: Exception) { finish(Result.failure(error)) }
            return AutoCloseable {
                fun cancel() { selection.close(); canceled(); dialog?.dismiss() }
                if (Looper.myLooper() == Looper.getMainLooper()) cancel()
                else Handler(Looper.getMainLooper()).post { cancel() }
            }
        }
    }
}
