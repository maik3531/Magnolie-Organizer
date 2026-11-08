package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Activity
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
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
import java.util.concurrent.atomic.AtomicBoolean

/** OS write permission only. No flag from a peer, RESULT_OK alone, saved intent,
 * archive, or READ lease can construct a usable native write grant. */
internal class NativeGalleryWriteRequest private constructor(internal val entry: NativeGalleryArchiveEntry,
    internal val permit: NativeGalleryTrashBookPermit, internal val uri: Uri, private val intent: PendingIntent,
    internal val mediaType: GalleryMediaType,
    private val observed: NativePhotoReceiver, private val current: () -> NativePhotoReceiver?,
    private val elapsed: () -> Long) {
    private val issued = elapsed()
    private var last = issued
    private var host: Any? = null
    private var launched = false
    private var completed = false
    private var invalid = false

    @Synchronized internal fun requireCurrent() {
        try {
            val now = elapsed(); val actual = current()
            if (invalid || now < issued || now < last || now - issued >= DeviceFileControl.MAX_TTL_MS || actual == null || !actual.allowed ||
                actual.owner !== observed.owner || actual.peerId != observed.peerId || actual.identitySha256 != observed.identitySha256 ||
                actual.permissionEpoch != observed.permissionEpoch || actual.pairingEpoch != observed.pairingEpoch)
                fail("gallery_write_request_not_current")
            permit.requireCurrent(); last = now
        } catch (error: Exception) { invalid = true; throw error }
    }
    @Synchronized internal fun launch(owner: Any): IntentSenderRequest {
        requireCurrent()
        if (launched || host != null || completed) fail("gallery_write_request_already_launched")
        host = owner; launched = true
        return IntentSenderRequest.Builder(intent.intentSender).build()
    }
    @Synchronized internal fun result(activity: ComponentActivity, owner: Any, code: Int): NativeGalleryWriteGrant {
        requireCurrent()
        if (host !== owner || !launched || completed) fail("gallery_write_request_wrong_result_owner")
        completed = true
        if (code != Activity.RESULT_OK || activity.checkUriPermission(uri, Process.myPid(), Process.myUid(), Intent.FLAG_GRANT_WRITE_URI_PERMISSION) != PackageManager.PERMISSION_GRANTED)
            fail("gallery_write_os_permission_not_granted")
        return NativeGalleryWriteGrant(this, activity, owner)
    }
    @Synchronized internal fun requireHost(owner: Any) {
        requireCurrent()
        if (host !== owner || !completed) fail("gallery_write_request_wrong_result_owner")
    }
    @Synchronized internal fun revoke() { invalid = true }

    companion object {
        internal fun prepare(context: android.content.Context, archive: NativeGalleryTrashArchive, entry: NativeGalleryArchiveEntry,
            permit: NativeGalleryTrashBookPermit, current: () -> NativePhotoReceiver?,
            elapsed: () -> Long = { DeviceFileControl.monotonicMs() }): NativeGalleryWriteRequest {
            if (Build.VERSION.SDK_INT < 30) fail("gallery_write_android30_required")
            permit.requireTrashEnabled()
            val observed = current()?.takeIf { it.allowed } ?: fail("gallery_write_native_receiver_required")
            if (observed.pairingEpoch?.let(DeviceFileControl::hash) != true) fail("gallery_write_current_pairing_required")
            val origin = archive.verifiedOriginalOrigin(entry, permit)
            if (origin.string("peer") != observed.peerId || origin.string("peer_identity") != observed.identitySha256)
                fail("gallery_write_original_peer_required")
            val uri = Uri.parse(origin.string("uri"))
            // Unlike createTrashRequest this does NOT mutate while the user is
            // in the OS dialog. Original bytes/row are revalidated afterwards.
            val pending = MediaStore.createWriteRequest(context.contentResolver, listOf(uri))
            val kind = GalleryMediaType.entries.single { it.uriSegment == origin.string("media_type") }
            return NativeGalleryWriteRequest(entry, permit, uri, pending, kind, observed, current, elapsed).also { it.requireCurrent() }
        }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}

internal class NativeGalleryWriteGrant internal constructor(internal val request: NativeGalleryWriteRequest,
    private val activity: ComponentActivity, private val host: Any) {
    private val used = AtomicBoolean(false)
    internal fun requireCurrent() {
        request.requireHost(host)
        if (!activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) || activity.isFinishing || activity.isDestroyed ||
            activity.checkUriPermission(request.uri, Process.myPid(), Process.myUid(), Intent.FLAG_GRANT_WRITE_URI_PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            request.revoke(); throw PhotoFolderScopeError("gallery_write_os_permission_not_current")
        }
    }
    internal fun consume() {
        requireCurrent()
        if (!used.compareAndSet(false, true)) throw PhotoFolderScopeError("gallery_write_grant_already_used")
    }
}

/** Early Activity owner, request-specific registry keys. The non-lifecycle
 * registry overload is explicitly owned/unregistered here; a new request never
 * reuses an old result code. No Activity/draft recreation or late lifecycle-owner
 * registration. Retiring a pending request retains its slot until its result. */
internal class NativeGalleryWriteConsentHost(private val activity: ComponentActivity,
    private val readPermissionPending: () -> Boolean = { false }) : DefaultLifecycleObserver, AutoCloseable {
    private class Pending(val request: NativeGalleryWriteRequest, val result: (Result<NativeGalleryWriteGrant>) -> Unit) {
        var launcher: ActivityResultLauncher<IntentSenderRequest>? = null
    }
    private class OriginalPending(val request: NativeGalleryOriginalAccessRequest, val result: (Result<Unit>) -> Unit) {
        var launcher: ActivityResultLauncher<String>? = null
    }
    private val owner = Any()
    private var pending: Pending? = null
    private var originalPending: OriginalPending? = null
    private var granted: NativeGalleryWriteRequest? = null
    private var closed = false
    private fun complete(held: Pending, code: Int) {
        if (pending !== held) return
        pending = null
        held.launcher?.unregister(); held.launcher = null
        val outcome = runCatching { held.request.result(activity, owner, code) }
        if (closed) { held.request.revoke(); return }
        if (outcome.isSuccess) granted = held.request
        // ActivityResult may arrive before onResume/access-epoch rotation. Post
        // delivery so a successful receiver must resolve a FRESH native source.
        android.os.Handler(Looper.getMainLooper()).post {
            if (closed) held.request.revoke()
            else held.result(outcome)
        }
    }
    init { activity.lifecycle.addObserver(this) }
    internal val requestPending: Boolean get() = pending != null || originalPending != null
    fun requestOriginal(request: NativeGalleryOriginalAccessRequest, result: (Result<Unit>) -> Unit) {
        uiThread()
        if (closed || !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) throw PhotoFolderScopeError("gallery_write_foreground_required")
        if (requestPending || readPermissionPending()) throw PhotoFolderScopeError("gallery_write_request_pending")
        granted?.revoke(); granted = null
        val held = OriginalPending(request, result); originalPending = held
        try {
            held.launcher = activity.activityResultRegistry.register("native-gallery-original-" + java.util.UUID.randomUUID(),
                ActivityResultContracts.RequestPermission()) { reported ->
                if (originalPending === held) {
                    originalPending = null; held.launcher?.unregister(); held.launcher = null
                    val outcome = runCatching { request.result(activity, owner, reported) }
                    android.os.Handler(Looper.getMainLooper()).post {
                        if (closed) request.revoke() else {
                            val current = runCatching { request.requireCurrent(); outcome.getOrThrow() }
                            request.revoke(); result(current)
                        }
                    }
                }
            }
            held.launcher!!.launch(request.launch(owner))
        } catch (error: Exception) { originalPending = null; held.launcher?.unregister(); request.revoke(); throw error }
    }
    fun request(request: NativeGalleryWriteRequest, result: (Result<NativeGalleryWriteGrant>) -> Unit) {
        uiThread()
        if (closed || !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) throw PhotoFolderScopeError("gallery_write_foreground_required")
        if (requestPending || readPermissionPending()) throw PhotoFolderScopeError("gallery_write_request_pending")
        granted?.revoke(); granted = null
        val held = Pending(request, result); pending = held
        try {
            held.launcher = activity.activityResultRegistry.register("native-gallery-write-" + java.util.UUID.randomUUID(),
                ActivityResultContracts.StartIntentSenderForResult()) { value -> complete(held, value.resultCode) }
            held.launcher!!.launch(request.launch(owner))
        } catch (error: Exception) { pending = null; held.launcher?.unregister(); request.revoke(); throw error }
    }
    fun retirePending() { uiThread(); pending?.request?.revoke(); originalPending?.request?.revoke(); granted?.revoke(); granted = null }
    override fun onPause(owner: LifecycleOwner) { granted?.revoke(); granted = null }
    override fun onDestroy(owner: LifecycleOwner) { close() }
    override fun close() {
        uiThread()
        if (closed) return
        closed = true; pending?.request?.revoke(); granted?.revoke(); granted = null
        originalPending?.request?.revoke(); originalPending?.launcher?.unregister()
        pending?.launcher?.unregister(); activity.lifecycle.removeObserver(this)
    }
    private fun uiThread() {
        if (Looper.myLooper() != Looper.getMainLooper()) throw PhotoFolderScopeError("gallery_permission_ui_thread_required")
    }
}
