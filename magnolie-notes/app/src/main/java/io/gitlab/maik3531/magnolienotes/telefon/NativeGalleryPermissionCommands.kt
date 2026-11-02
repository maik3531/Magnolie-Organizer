package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject

/** Process-local UI-command receipts, not OS READ or transfer receipts. The
 * native transport owner shares this across reconnects to avoid another prompt
 * after a lost response. Scope is derived from authenticated native identities
 * and pairing, never restored from a request. No persistent personal store.
 */
internal class NativeGalleryPermissionCommands(private val wallMs: () -> Long = { System.currentTimeMillis() },
    private val monotonicMs: () -> Long = { DeviceFileControl.monotonicMs() }) {
    private class Entry(val digest: String, val expires: Long, val commandExpires: Long, var state: String = "failed")
    private val entries = linkedMapOf<Pair<String, String>, Entry>()
    private var last = -1L
    private var lastWall = -1L
    private var faulted = false

    @Synchronized fun execute(scope: String, command: DeviceFileSourceCommand, message: JsonObject, launch: () -> String): String {
        if (faulted || !DeviceFileControl.hash(scope) || command.operation != "request_read") DeviceFileControl.fail("gallery_permission_command_not_current")
        val now = monotonicMs()
        val wall = wallMs()
        if (now < 0 || now < last || wall < 0 || wall < lastWall || now > Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS) {
            faulted = true; DeviceFileControl.fail("gallery_permission_command_not_current")
        }
        last = now
        lastWall = wall
        // Clock skew may keep the original envelope live longer than sixty
        // seconds after receipt. Never evict its replay fence while it can still
        // be accepted; bounded capacity fails closed instead. A wall rollback
        // permanently fences the process-local history, including after pruning.
        entries.entries.removeAll { it.value.expires <= now && it.value.commandExpires <= wall }
        val key = scope to command.requestId
        val digest = DeviceFileControl.digest("magnolie-gallery-permission-command-v1\u0000", message)
        entries[key]?.let {
            if (it.digest != digest) DeviceFileControl.fail("gallery_permission_command_id_reused")
            return it.state
        }
        if (entries.size >= 64) DeviceFileControl.fail("gallery_permission_commands_held")
        // Hold failure evidence BEFORE the native UI call. An exception or lost
        // reply must not make the same request launch another system prompt.
        val held = Entry(digest, now + DeviceFileControl.MAX_TTL_MS, command.expires)
        entries[key] = held
        val state = launch()
        if (state !in STATES) DeviceFileControl.fail("gallery_permission_command_invalid_result")
        held.state = state
        return state
    }

    companion object { val STATES = setOf("requested", "notification_posted", "foreground_required", "failed") }
}
