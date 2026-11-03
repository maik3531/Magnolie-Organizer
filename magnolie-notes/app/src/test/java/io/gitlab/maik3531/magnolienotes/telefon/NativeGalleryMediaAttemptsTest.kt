package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class NativeGalleryMediaAttemptsTest {
    private val now = 1_800_000_000_000L
    private fun message() = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
        put("format", 1); put("operation", "media_page"); put("expected_version", "a".repeat(64))
        put("run_id", "33333333-3333-4333-8333-333333333333"); put("after", 0)
    }, 60_000, now)
    private fun check(attempts: NativeGalleryMediaAttempts, message: JsonObject, wall: Long = now, elapsed: Long = 100) =
        attempts.check(DeviceFileSourceCommand.parse(message, now), message, wall, elapsed)

    @Test fun exactLostOutputRetryKeepsOriginalAttemptButChangedEnvelopeCannotAdoptIt() {
        val attempts = NativeGalleryMediaAttempts(); val first = message()
        check(attempts, first); check(attempts, first, now + 1, 101)
        val changed = JsonObject(first + ("created_ms" to JsonPrimitive(now + 1)))
        assertThrows(PhotoFolderScopeError::class.java) { check(attempts, changed, now + 1, 102) }
        check(attempts, first, now + 2, 103)
    }

    @Test fun originalWallAndMonotonicDeadlinesCannotBeRefreshedByRetry() {
        for ((wall, elapsed) in listOf(now + 60_000 to 101L, now + 1 to 60_100L)) {
            val attempts = NativeGalleryMediaAttempts(); val first = message()
            check(attempts, first)
            assertThrows(PhotoFolderScopeError::class.java) { check(attempts, first, wall, elapsed) }
            assertThrows(PhotoFolderScopeError::class.java) { check(attempts, first, wall + 1, elapsed + 1) }
        }
    }

    @Test fun observedRunClockRollbackFencesOldAndNewPageAttempts() {
        for ((wall, elapsed) in listOf(now - 1 to 101L, now to 99L)) {
            val attempts = NativeGalleryMediaAttempts(); val first = message()
            check(attempts, first)
            assertThrows(PhotoFolderScopeError::class.java) { check(attempts, first, wall, elapsed) }
            assertThrows(PhotoFolderScopeError::class.java) { check(attempts, message(), now + 1, 102) }
        }
    }

    @Test fun boundedRegistryDoesNotEvictOriginalAttemptAtCapacity() {
        val attempts = NativeGalleryMediaAttempts(); val first = message()
        check(attempts, first)
        repeat(127) { check(attempts, message(), now, 101L + it) }
        assertThrows(PhotoFolderScopeError::class.java) { check(attempts, message(), now, 228) }
        check(attempts, first, now, 229)
    }

    @Test fun shortOrPartlyElapsedMediaCommandCannotGainSixtySecondsOnFrozenWallRetry() {
        for ((wall, ttl) in listOf(now to 1000L, now + 59_500L to 500L)) {
            val attempts = NativeGalleryMediaAttempts()
            val original = message()
            val first = if (wall == now) JsonObject(original + ("expires_ms" to JsonPrimitive(now + ttl))) else original
            check(attempts, first, wall, 100L)
            check(attempts, first, wall, 100L + ttl - 1)
            assertThrows(PhotoFolderScopeError::class.java) { check(attempts, first, wall, 100L + ttl) }
            assertThrows(PhotoFolderScopeError::class.java) { check(attempts, first, wall, 100L + ttl - 1) }
        }
    }
}
