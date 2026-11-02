package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.os.Build
import android.os.SystemClock
import java.security.SecureRandom
import java.util.Locale

internal class GalleryPhotoPermissionTicket internal constructor(internal val activation: NativeGalleryRequest,
    internal val startedMs: Long, permissions: List<String>) {
    val permissions: List<String> = java.util.Collections.unmodifiableList(permissions.toList())
}

/** Native-only permission lifecycle, not remotely supplied access epochs.
 * The activity adapter must call foreground/resume hooks and pass its genuine
 * RequestMultiplePermissions launcher. No settings UI, automatic prompt, writes,
 * permission revocation, notification or background activity launch is added here.
 */
internal class GalleryPhotoAccessController(context: Context, private val current: () -> NativeGalleryRequest?,
    private val elapsedMs: () -> Long = { SystemClock.elapsedRealtime() }) {
    private val app = context.applicationContext
    private var epoch = nonce()
    private var pending: GalleryPhotoPermissionTicket? = null
    private var launched = false
    private var foreground = false
    private var resumedOnce = false
    private var closed = false

    val environment: GalleryAccessEnvironment = AndroidGalleryAccessEnvironment(app) { accessEpoch() }

    @Synchronized fun accessEpoch(): String {
        if (closed) fail("gallery_access_controller_closed")
        return epoch
    }

    /** Called by native activity lifecycle, never by a peer message. Every
     * return from background rotates proofs, even when selected-photo changes
     * leave the coarse Android permission flags identical.
     */
    @Synchronized fun onResume() {
        if (closed) fail("gallery_access_controller_closed")
        if (!foreground && resumedOnce) rotate()
        foreground = true
        resumedOnce = true
    }

    @Synchronized fun onPause() { foreground = false }

    /** Call for native permission/result/selected-photo-change notifications.
     * Rotation does not release app-wide URI or backup/import rights.
     */
    @Synchronized fun onAccessChanged() {
        if (closed) fail("gallery_access_controller_closed")
        rotate()
    }

    @Synchronized fun preparePermissionRequest(): GalleryPhotoPermissionTicket {
        ready()
        if (!foreground) fail("gallery_permission_foreground_required")
        if (pending != null) fail("gallery_permission_request_pending")
        val activation = current() ?: fail("gallery_source_not_activated")
        if (!activation.receiver.allowed || activation.kinds.isEmpty()) fail("gallery_receiver_not_ready")
        val permissions = when {
            Build.VERSION.SDK_INT >= 34 -> listOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            Build.VERSION.SDK_INT >= 33 -> listOf(Manifest.permission.READ_MEDIA_IMAGES)
            else -> listOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        rotate()
        return GalleryPhotoPermissionTicket(activation, elapsedMs(), permissions).also { pending = it; launched = false }
    }

    @Synchronized fun launch(ticket: GalleryPhotoPermissionTicket, launcher: (Array<String>) -> Unit) {
        ready()
        if (pending !== ticket || launched) fail("gallery_permission_stale_ticket")
        if (!foreground) fail("gallery_permission_foreground_required")
        if (!valid(ticket)) { cancel(); fail("gallery_permission_source_changed") }
        launched = true
        try {
            launcher(ticket.permissions.toTypedArray())
        } catch (error: Exception) {
            cancel()
            throw error
        }
    }

    /** Ignore the launcher's Boolean/map as authority: read actual OS flags.
     * Result may update only the exact still-current native policy/receiver.
     */
    @Synchronized fun complete(ticket: GalleryPhotoPermissionTicket): GalleryReadCoverage {
        ready()
        if (pending !== ticket || !launched) fail("gallery_permission_stale_ticket")
        val allowed = valid(ticket)
        cancel()
        if (!allowed) fail("gallery_permission_source_changed")
        val coverage = AndroidGalleryReadPermissions.observe(app)
        if (!same(ticket.activation, current())) fail("gallery_permission_source_changed")
        return coverage
    }

    @Synchronized fun cancel() { pending = null; launched = false; rotate() }

    @Synchronized fun close() { cancel(); foreground = false; closed = true }

    private fun valid(ticket: GalleryPhotoPermissionTicket): Boolean {
        val now = elapsedMs()
        return now >= ticket.startedMs && now - ticket.startedMs <= MAX_PROMPT_MS && same(ticket.activation, current())
    }
    private fun same(first: NativeGalleryRequest, second: NativeGalleryRequest?): Boolean = second != null &&
        first.receiver.allowed && second.receiver.allowed && first.kinds == second.kinds && first.policyEpoch == second.policyEpoch &&
        first.receiver.owner === second.receiver.owner && first.receiver.peerId == second.receiver.peerId &&
        first.receiver.identitySha256 == second.receiver.identitySha256 && first.receiver.permissionEpoch == second.receiver.permissionEpoch
    private fun ready() { if (closed) fail("gallery_access_controller_closed") }
    private fun rotate() { epoch = nonce() }

    companion object {
        const val MAX_PROMPT_MS = 120_000L
        private fun nonce() = ByteArray(32).also(SecureRandom()::nextBytes)
            .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
