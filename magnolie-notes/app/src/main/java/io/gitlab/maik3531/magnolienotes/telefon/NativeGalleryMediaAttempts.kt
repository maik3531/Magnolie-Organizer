package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject

/** Bounded exact metadata attempts owned by one native run. No eviction or
 * replacement on failed output; fresh explicit page requests are not scans. */
internal class NativeGalleryMediaAttempts {
    private data class Attempt(val digest: String, val expiresWall: Long, val expiresElapsed: Long, var invalid: Boolean = false)
    private val attempts = mutableMapOf<String, Attempt>()
    private var lastWall: Long? = null
    private var lastElapsed: Long? = null
    private var clockInvalid = false

    fun check(command: DeviceFileSourceCommand, message: JsonObject, wall: Long,
        elapsed: Long = DeviceFileControl.monotonicMs()) {
        if (clockInvalid || wall < 0 || elapsed < 0 || lastWall?.let { wall < it } == true || lastElapsed?.let { elapsed < it } == true) {
            clockInvalid = true; DeviceFileControl.fail("gallery_media_attempt_clock_changed")
        }
        lastWall = wall; lastElapsed = elapsed
        val digest = DeviceFileControl.digest("magnolie-gallery-media-command-v1\u0000", message)
        val held = attempts[command.requestId] ?: run {
            if (attempts.size >= 128 || elapsed > Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS)
                DeviceFileControl.fail("gallery_media_attempt_limit")
            Attempt(digest, command.expires, elapsed + DeviceFileControl.MAX_TTL_MS).also { attempts[command.requestId] = it }
        }
        if (held.digest != digest) DeviceFileControl.fail("gallery_media_attempt_changed")
        if (held.invalid || wall >= held.expiresWall || elapsed >= held.expiresElapsed) {
            held.invalid = true; DeviceFileControl.fail("gallery_media_attempt_expired")
        }
    }
}
