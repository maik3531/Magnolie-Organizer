package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.ComponentActivity

/** Explicit recovery-only permission request. A successful callback is NOT a
 * source lease, original-byte witness, archive or OS mutation permission. */
internal class NativeGalleryOriginalAccessRequest private constructor(private val permit: NativeGalleryTrashBookPermit,
    private val observed: NativeGalleryRequest, private val current: () -> NativeGalleryRequest?) {
    private val issued = DeviceFileControl.monotonicMs()
    private var last = issued
    private var revoked = false
    private var owner: Any? = null
    private var completed = false
    @Synchronized internal fun requireCurrent() {
        try {
            val now = DeviceFileControl.monotonicMs(); val actual = current()
            val first = observed.receiver; val second = actual?.receiver
            if (revoked || now < issued || now < last || now - issued >= DeviceFileControl.MAX_TTL_MS || actual == null ||
                !first.allowed || second?.allowed != true || first.owner !== second.owner || first.peerId != second.peerId ||
                first.identitySha256 != second.identitySha256 || first.permissionEpoch != second.permissionEpoch || first.pairingEpoch != second.pairingEpoch ||
                observed.policyEpoch != actual.policyEpoch || observed.mediaIntent !== actual.mediaIntent || observed.mediaType != actual.mediaType || observed.kinds != actual.kinds)
                fail("gallery_original_access_not_current")
            permit.requireCurrent(); last = now
        } catch (error: Exception) { revoked = true; throw error }
    }
    @Synchronized internal fun launch(host: Any): String {
        requireCurrent()
        if (owner != null || completed) fail("gallery_original_access_already_launched")
        owner = host
        return Manifest.permission.ACCESS_MEDIA_LOCATION
    }
    @Synchronized internal fun result(activity: ComponentActivity, host: Any, reported: Boolean) {
        requireCurrent()
        if (owner !== host || completed) fail("gallery_original_access_wrong_owner")
        completed = true
        if (!reported || activity.isFinishing || activity.isDestroyed ||
            activity.checkSelfPermission(Manifest.permission.ACCESS_MEDIA_LOCATION) != PackageManager.PERMISSION_GRANTED)
            fail("gallery_original_access_not_granted")
    }
    @Synchronized internal fun revoke() { revoked = true }
    companion object {
        fun prepare(permit: NativeGalleryTrashBookPermit, current: () -> NativeGalleryRequest?): NativeGalleryOriginalAccessRequest {
            if (Build.VERSION.SDK_INT < 30) fail("gallery_archive_native_origin_required")
            val observed = current() ?: fail("gallery_write_native_receiver_required")
            if (observed.receiver.pairingEpoch?.let(DeviceFileControl::hash) != true) fail("gallery_write_current_pairing_required")
            return NativeGalleryOriginalAccessRequest(permit, observed, current).also { it.requireCurrent() }
        }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
