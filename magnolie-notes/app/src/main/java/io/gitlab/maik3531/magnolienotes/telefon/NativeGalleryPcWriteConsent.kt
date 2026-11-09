package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Activity
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.CancellationSignal
import android.os.Looper
import android.os.Process
import android.provider.MediaStore
import androidx.activity.ComponentActivity
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import kotlinx.serialization.json.*
import java.util.concurrent.atomic.AtomicBoolean

/** Original incoming-PC mutation admission. This owns no writer: an eventual
 * writer still needs an exact durable journal and fresh row/byte verification. */
internal class NativeGalleryPcWriteAdmission private constructor(private val session: NativeFileControlSession,
    private val index: PhotoSourceJobIndex, private val book: NativeGalleryReceiveBookPermit,
    internal val archiveBook: NativeGalleryTrashBookPermit, private val peer: () -> NativeFileControlPeer?,
    private val incomingIntent: () -> Any?, internal val publication: GalleryIncomingPublication) : AutoCloseable {
    private val originalPeer = peer() ?: fail()
    private val kind = GalleryMediaType.entries.single { it.uriSegment == publication.body.string("media_type") }
    private val policy = index.galleryPolicy()
    private val action = NativeGalleryPcArchiveAction.capture(session, kind, book, archiveBook, incomingIntent) { true }
    init { requireCurrent() }
    internal fun requireCurrent() {
        try {
            action.requireCurrent()
            if (publication.pcOrigin == null || publication.state != "published" || publication.row == null ||
                peer() != originalPeer || peer()?.owner !== originalPeer.owner || index.galleryPolicy() != policy ||
                index.incomingPublication(publication.id)?.body != publication.body) fail()
        } catch (error: Exception) { close(); throw error }
    }
    internal fun inspection(): NativeGalleryPublishedInspection {
        requireCurrent()
        val destination = publication.body.getValue("origin").jsonObject.string("manifest_sha256")
        return NativeGalleryPublishedInspection.capture(session, index, book, peer, {
            requireCurrent(); action.currentIntent()
        }, publication, expectedControl = action.expectedControl(destination))
    }
    internal fun bindCancellation(cancellation: CancellationSignal) { action.bindCancellation(cancellation) }
    internal fun requireOwner(owner: NativeGalleryPublishedInspection, permit: NativeGalleryTrashBookPermit) {
        requireCurrent()
        if (permit !== archiveBook || owner.selected.body != publication.body) { close(); fail() }
        owner.requireArchiveBook(permit)
    }
    override fun close() { action.close() }
    companion object {
        internal fun capture(session: NativeFileControlSession, index: PhotoSourceJobIndex,
            book: NativeGalleryReceiveBookPermit, archiveBook: NativeGalleryTrashBookPermit,
            peer: () -> NativeFileControlPeer?, incomingIntent: () -> Any?, publication: GalleryIncomingPublication): NativeGalleryPcWriteAdmission {
            if (Looper.myLooper() == Looper.getMainLooper() || Build.VERSION.SDK_INT < 30) fail()
            return NativeGalleryPcWriteAdmission(session, index, book, archiveBook, peer, incomingIntent, publication)
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_pc_write_original_admission_required")
    }
}

/** OS permission request only, constructed inside the actual verified PC row
 * archive completion. No synthetic outbound phone source or replacement ACK. */
internal class NativeGalleryPcWriteRequest private constructor(internal val admission: NativeGalleryPcWriteAdmission,
    internal val entry: NativeGalleryArchiveEntry, internal val uri: Uri, private val intent: PendingIntent) : AutoCloseable {
    private var host: Any? = null
    private var completed = false
    private val closed = AtomicBoolean(false)
    internal fun requireCurrent() {
        if (closed.get()) fail()
        try { admission.requireCurrent() } catch (error: Exception) { close(); throw error }
    }
    @Synchronized internal fun launch(owner: Any): IntentSenderRequest {
        requireCurrent()
        if (host != null || completed) fail()
        host = owner
        return IntentSenderRequest.Builder(intent.intentSender).build()
    }
    @Synchronized internal fun result(activity: ComponentActivity, owner: Any, code: Int): NativeGalleryPcWriteGrant {
        try {
            requireCurrent()
            if (host !== owner || completed) fail()
            completed = true
            if (code != Activity.RESULT_OK || activity.checkUriPermission(uri, Process.myPid(), Process.myUid(),
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION) != PackageManager.PERMISSION_GRANTED) fail()
            return NativeGalleryPcWriteGrant(this, activity, owner)
        } catch (error: Exception) { close(); throw error }
    }
    @Synchronized internal fun requireHost(owner: Any) {
        requireCurrent()
        if (host !== owner || !completed) fail()
    }
    override fun close() { closed.set(true); admission.close() }
    companion object {
        internal fun prepare(context: android.content.Context, rows: NativeGalleryIncomingRows, owner: NativeGalleryPublishedInspection,
            archive: NativeGalleryTrashArchive, permit: NativeGalleryTrashBookPermit, entry: NativeGalleryArchiveEntry,
            admission: NativeGalleryPcWriteAdmission): NativeGalleryPcWriteRequest {
            rows.requireVerifiedArchive(archive, owner, permit)
            admission.requireOwner(owner, permit)
            val origin = archive.verifiedOrigin(entry, permit)
            if (origin["publication"] != admission.publication.body || origin.string("book_version") != permit.version) fail()
            val uri = Uri.parse(admission.publication.row!!.string("uri"))
            val intent = MediaStore.createWriteRequest(context.contentResolver, listOf(uri))
            admission.requireCurrent()
            return NativeGalleryPcWriteRequest(admission, entry, uri, intent)
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_pc_write_os_owner_required")
    }
}

internal class NativeGalleryPcWriteGrant internal constructor(internal val request: NativeGalleryPcWriteRequest,
    private val activity: ComponentActivity, private val host: Any) {
    private val used = AtomicBoolean(false)
    internal fun requireCurrent() {
        request.requireHost(host)
        if (activity.isFinishing || activity.isDestroyed || !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) ||
            activity.checkUriPermission(request.uri, Process.myPid(), Process.myUid(), Intent.FLAG_GRANT_WRITE_URI_PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            request.close(); DeviceFileControl.fail("gallery_pc_write_os_owner_required")
        }
    }
    internal fun consume() {
        requireCurrent()
        if (!used.compareAndSet(false, true)) DeviceFileControl.fail("gallery_pc_write_grant_already_used")
    }
}

/** Request-specific registry ownership. An intentional pending OS dialog may
 * pause the Activity; no grant can be used until it is genuinely resumed. */
internal class NativeGalleryPcWriteConsentHost(private val activity: ComponentActivity,
    private val otherPermissionPending: () -> Boolean = { false }) : DefaultLifecycleObserver, AutoCloseable {
    private class Pending(val request: NativeGalleryPcWriteRequest, val result: (Result<NativeGalleryPcWriteGrant>) -> Unit) {
        var launcher: ActivityResultLauncher<IntentSenderRequest>? = null
    }
    private val owner = Any()
    private var pending: Pending? = null
    private var granted: NativeGalleryPcWriteRequest? = null
    private var closed = false
    init {
        check(Looper.myLooper() == Looper.getMainLooper())
        activity.lifecycle.addObserver(this)
    }
    internal val requestPending: Boolean get() = pending != null
    internal fun request(request: NativeGalleryPcWriteRequest, result: (Result<NativeGalleryPcWriteGrant>) -> Unit) {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (closed || pending != null || otherPermissionPending() || !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
            DeviceFileControl.fail("gallery_pc_write_host_not_current")
        granted?.close(); granted = null
        val held = Pending(request, result); pending = held
        try {
            held.launcher = activity.activityResultRegistry.register("native-pc-gallery-write-" + java.util.UUID.randomUUID(),
                ActivityResultContracts.StartIntentSenderForResult()) { value ->
                if (pending === held) {
                    pending = null; held.launcher?.unregister(); held.launcher = null
                    val outcome = runCatching { request.result(activity, owner, value.resultCode) }
                    if (closed) request.close() else {
                        if (outcome.isSuccess) granted = request
                        android.os.Handler(Looper.getMainLooper()).post {
                            if (closed) request.close() else result(outcome)
                        }
                    }
                }
            }
            held.launcher!!.launch(request.launch(owner))
        } catch (error: Exception) { pending = null; held.launcher?.unregister(); request.close(); throw error }
    }
    internal fun retirePending() {
        check(Looper.myLooper() == Looper.getMainLooper())
        pending?.request?.close(); granted?.close(); granted = null
    }
    override fun onPause(owner: LifecycleOwner) { granted?.close(); granted = null }
    override fun onDestroy(owner: LifecycleOwner) { close() }
    override fun close() {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (closed) return
        closed = true; retirePending(); pending?.launcher?.unregister(); activity.lifecycle.removeObserver(this)
    }
}
