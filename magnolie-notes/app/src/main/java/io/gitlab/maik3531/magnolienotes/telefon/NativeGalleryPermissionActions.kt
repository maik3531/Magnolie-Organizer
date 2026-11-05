package io.gitlab.maik3531.magnolienotes.telefon

import java.security.SecureRandom
import java.util.Locale

internal class NativeGalleryPermissionAction internal constructor(val token: String,
    internal val mediaType: GalleryMediaType = GalleryMediaType.IMAGES)
internal class NativeGalleryPermissionActionScope(val owner: Any, val request: NativeGalleryRequest)

/** Opaque in-memory permission-UI actions only, never serialized source/read
 * grants. Each action is bound to exact native runtime + source authority and
 * expires monotonically without refresh on repeated requests.
 */
internal class NativeGalleryPermissionActions(private val current: () -> NativeGalleryPermissionActionScope?,
    private val monotonicMs: () -> Long = { DeviceFileControl.monotonicMs() }) {
    private class Entry(val action: NativeGalleryPermissionAction, val scope: NativeGalleryPermissionActionScope,
        val issued: Long, val expires: Long)
    private var pending: Entry? = null

    @Synchronized fun create(): NativeGalleryPermissionAction {
        val scope = try { current()?.takeIf { it.request.receiver.allowed && it.request.kinds.isNotEmpty() } }
            catch (error: Exception) { pending = null; throw error }
        if (scope == null) { pending = null; DeviceFileControl.fail("gallery_permission_action_source_changed") }
        val now = monotonicMs()
        if (now < 0 || now > Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS) { pending = null; DeviceFileControl.fail("gallery_permission_action_expired") }
        pending?.let { if (now >= it.issued && now < it.expires && same(it.scope, scope)) return it.action }
        val token = ByteArray(32).also { SecureRandom().nextBytes(it) }
            .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        return NativeGalleryPermissionAction(token, scope.request.mediaType).also { pending = Entry(it, scope, now, now + DeviceFileControl.MAX_TTL_MS) }
    }

    @Synchronized fun isCurrent(token: String): Boolean = try { requireEntry(token); true }
        catch (_: PhotoFolderScopeError) { false }

    @Synchronized fun perform(token: String, launch: (Any) -> Unit) {
        val original = requireEntry(token)
        try { launch(original.scope.owner) }
        catch (error: Exception) {
            if (error !is PhotoFolderScopeError || error.code !in RETRYABLE) if (pending === original) pending = null
            throw error
        }
        if (pending === original) pending = null
    }

    @Synchronized fun cancelOwner(owner: Any) { if (pending?.scope?.owner === owner) pending = null }

    private fun requireEntry(token: String): Entry {
        val value = pending?.takeIf { DeviceFileControl.hash(token) && it.action.token == token }
            ?: DeviceFileControl.fail("gallery_permission_action_unknown")
        try {
            val now = monotonicMs()
            if (now < value.issued || now >= value.expires) DeviceFileControl.fail("gallery_permission_action_expired")
            val live = current() ?: DeviceFileControl.fail("gallery_permission_action_source_changed")
            if (!same(value.scope, live)) DeviceFileControl.fail("gallery_permission_action_source_changed")
            return value
        } catch (error: Exception) { if (pending === value) pending = null; throw error }
    }

    private fun same(first: NativeGalleryPermissionActionScope, second: NativeGalleryPermissionActionScope): Boolean {
        val before = first.request; val after = second.request
        val a = before.receiver; val b = after.receiver
        return first.owner === second.owner && a.allowed && b.allowed && before.kinds == after.kinds && before.policyEpoch == after.policyEpoch && before.mediaIntent === after.mediaIntent &&
            before.mediaType == after.mediaType &&
            a.owner === b.owner && a.peerId == b.peerId && a.identitySha256 == b.identitySha256 &&
            a.permissionEpoch == b.permissionEpoch && a.pairingEpoch == b.pairingEpoch
    }

    companion object {
        val RETRYABLE = setOf("gallery_workflow_permission_host_missing", "gallery_permission_foreground_required", "gallery_permission_request_pending")
    }
}
