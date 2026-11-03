package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class NativeGalleryWireOfferAttemptTest {
    private fun attempt() = NativeGalleryWireOfferAttempt("request", "a".repeat(64),
        buildJsonObject { put("expires_ms", 61_000L) }, 1_000L, 100L)

    @Test fun originalEnvelopeAndCommandIdentityRemainHeldAcrossChecks() {
        val held = attempt()
        val envelope = held.message
        held.checkCurrent(1_001L, 101L)
        held.checkCurrent(1_001L, 101L)
        assertSame(envelope, held.message)
        assertEquals("request", held.requestId)
        assertEquals("a".repeat(64), held.commandSha256)
    }

    @Test fun observedWallOrMonotonicRollbackAndBothDeadlinesPermanentlyFenceAttempt() {
        for ((wall, elapsed) in listOf(1_999L to 201L, 2_001L to 199L,
            61_000L to 201L, 2_001L to 60_100L)) {
            val held = attempt()
            held.checkCurrent(2_000L, 200L)
            assertThrows(PhotoFolderScopeError::class.java) { held.checkCurrent(wall, elapsed) }
            assertThrows(PhotoFolderScopeError::class.java) { held.checkCurrent(2_001L, 201L) }
        }
    }

    @Test fun invalidNativeMonotonicOriginCannotCreateAnAttempt() {
        for (elapsed in listOf(-1L, Long.MAX_VALUE)) {
            assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryWireOfferAttempt("request", "digest", buildJsonObject { put("expires_ms", 61_000L) }, 1_000L, elapsed)
            }
        }
    }

    @Test fun shortOrPartlyElapsedEnvelopeUsesOnlyRemainingMonotonicLifetimeUnderFrozenWall() {
        for ((wall, expires, ttl) in listOf(Triple(1000L, 2000L, 1000L), Triple(60_500L, 61_000L, 500L))) {
            val held = NativeGalleryWireOfferAttempt("request", "digest", buildJsonObject { put("expires_ms", expires) }, wall, 100L)
            held.checkCurrent(wall, 100L + ttl - 1)
            assertThrows(PhotoFolderScopeError::class.java) { held.checkCurrent(wall, 100L + ttl) }
            assertThrows(PhotoFolderScopeError::class.java) { held.checkCurrent(wall, 100L + ttl - 1) }
        }
    }

    @Test fun negativeOrExhaustedWallOriginCannotMintAnotherRemainingLifetime() {
        for (wall in listOf(-1L, 61_000L, 61_001L)) assertThrows(PhotoFolderScopeError::class.java) {
            NativeGalleryWireOfferAttempt("request", "digest", buildJsonObject { put("expires_ms", 61_000L) }, wall, 100L)
        }
    }
}
