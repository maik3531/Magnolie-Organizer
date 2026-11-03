package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject

/** Process-local explicit resume start fence. Never restores a disk attempt or
 * native source ownership after reconnect. Held before any worker launch. */
internal class NativeGalleryResumeCommands(private val wallMs: () -> Long = System::currentTimeMillis,
    private val elapsed: () -> Long = DeviceFileControl::monotonicMs) {
    private class Entry(val digest: String, val owner: Any, val deadline: Long, val expires: Long,
        var run: NativeGalleryResumeRun? = null)
    private val entries = linkedMapOf<Pair<String, String>, Entry>()
    private var lastWall = -1L
    private var lastElapsed = -1L
    private var faulted = false

    @Synchronized fun start(scope: String, owner: Any, command: DeviceFileSourceCommand, message: JsonObject,
        launch: () -> NativeGalleryResumeRun): NativeGalleryResumeRun {
        val tick = elapsed(); val wall = wallMs()
        if (faulted || !DeviceFileControl.hash(scope) || command.operation != "resume_run" || tick < 0 || tick < lastElapsed ||
            wall < 0 || wall < lastWall || tick > Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS) {
            faulted = true; DeviceFileControl.fail("gallery_resume_command_not_current")
        }
        lastWall = wall; lastElapsed = tick
        if (wall >= command.expires) DeviceFileControl.fail("gallery_resume_command_expired")
        entries.entries.removeAll { it.value.deadline <= tick && it.value.expires <= wall }
        val key = scope to command.requestId
        val digest = DeviceFileControl.digest("magnolie-gallery-resume-command-v1\u0000", message)
        entries[key]?.let {
            if (it.digest != digest) DeviceFileControl.fail("gallery_resume_command_id_reused")
            if (it.owner !== owner) DeviceFileControl.fail("gallery_resume_prior_owner_ended")
            return it.run ?: DeviceFileControl.fail("gallery_resume_prior_start_failed")
        }
        if (entries.size >= 64) DeviceFileControl.fail("gallery_resume_commands_held")
        val held = Entry(digest, owner, tick + DeviceFileControl.MAX_TTL_MS, command.expires)
        entries[key] = held
        return launch().also { held.run = it }
    }
}
