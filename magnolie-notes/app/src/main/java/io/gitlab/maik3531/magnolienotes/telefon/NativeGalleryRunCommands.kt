package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject

/** Process-local start replay fence. An ended runtime's command cannot launch
 * another scan on reconnect. This ledger neither restores authority nor owns
 * persistent source quota. Failed attempts are held before entering native work.
 */
internal class NativeGalleryRunCommands(private val wallMs: () -> Long = { System.currentTimeMillis() },
    private val monotonicMs: () -> Long = { DeviceFileControl.monotonicMs() }) {
    private class Entry(val digest: String, val owner: Any, val expires: Long, val commandExpires: Long, var run: NativeGallerySyncRun? = null)
    private val entries = linkedMapOf<Pair<String, String>, Entry>()
    private var last = -1L
    private var lastWall = -1L
    private var faulted = false

    @Synchronized fun start(scope: String, owner: Any, command: DeviceFileSourceCommand, message: JsonObject,
        launch: () -> NativeGallerySyncRun): NativeGallerySyncRun {
        val now = monotonicMs()
        val wall = wallMs()
        if (faulted || !DeviceFileControl.hash(scope) || command.operation !in setOf("run", "select_run") || now < 0 || now < last || wall < 0 || wall < lastWall ||
            now > Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS) {
            faulted = true; DeviceFileControl.fail("gallery_sync_run_command_not_current")
        }
        last = now
        lastWall = wall
        entries.entries.removeAll { it.value.expires <= now && it.value.commandExpires <= wall }
        val key = scope to command.requestId
        val digest = DeviceFileControl.digest("magnolie-gallery-run-command-v1\u0000", message)
        entries[key]?.let {
            if (it.digest != digest) DeviceFileControl.fail("gallery_sync_run_command_id_reused")
            if (it.owner !== owner) DeviceFileControl.fail("gallery_sync_run_prior_owner_ended")
            return it.run ?: DeviceFileControl.fail("gallery_sync_run_prior_start_failed")
        }
        if (entries.size >= 64) DeviceFileControl.fail("gallery_sync_run_commands_held")
        val entry = Entry(digest, owner, now + DeviceFileControl.MAX_TTL_MS, command.expires)
        entries[key] = entry
        return launch().also { entry.run = it }
    }
}
