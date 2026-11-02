package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class NativeGalleryPermissionCommandsTest {
    private val now = 1_800_000_000_000L
    private fun message(id: String = java.util.UUID.randomUUID().toString(), version: String = "a".repeat(64)) =
        TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
            put("format", 1); put("operation", "request_read"); put("expected_version", version)
        }, 60_000, now, id)

    @Test fun exactReplayOnTheSharedNativeScopeDoesNotLaunchAgainAfterLostReplyOrReconnect() {
        val ledger = NativeGalleryPermissionCommands { 100 }
        val original = message(); val command = DeviceFileSourceCommand.parse(original, now)
        var prompts = 0
        assertEquals("requested", ledger.execute("b".repeat(64), command, original) { prompts++; "requested" })
        val retry = Json.parseToJsonElement(TelefonKanonisch.text(original)).jsonObject
        assertEquals("requested", ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(retry, now), retry) { prompts++; "requested" })
        assertEquals(1, prompts)
    }

    @Test fun sameRequestIdWithDifferentCommandBytesIsRejectedRatherThanReassigned() {
        val ledger = NativeGalleryPermissionCommands { 100 }; val original = message()
        ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(original, now), original) { "foreground_required" }
        val changed = message(original.string("message_id"), "c".repeat(64))
        assertThrows(PhotoFolderScopeError::class.java) {
            ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(changed, now), changed) { throw AssertionError("Reused ID launched") }
        }
    }

    @Test fun aFailedNativeUiCallRetainsFailureEvidenceInsteadOfTryingTheSameCommandAgain() {
        val ledger = NativeGalleryPermissionCommands { 100 }; val message = message(); val command = DeviceFileSourceCommand.parse(message, now)
        assertThrows(IOException::class.java) { ledger.execute("b".repeat(64), command, message) { throw IOException("native UI failed") } }
        assertEquals("failed", ledger.execute("b".repeat(64), command, message) { throw AssertionError("Failed command retried") })
    }

    @Test fun commandReceiptsAreBoundedAndClockRollbackFailsClosed() {
        var clock = 100L; val ledger = NativeGalleryPermissionCommands { clock }
        repeat(64) {
            val message = message()
            ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(message, now), message) { "foreground_required" }
        }
        val extra = message(); val command = DeviceFileSourceCommand.parse(extra, now)
        assertThrows(PhotoFolderScopeError::class.java) { ledger.execute("b".repeat(64), command, extra) { throw AssertionError("Quota bypass") } }
        clock--
        assertThrows(PhotoFolderScopeError::class.java) { ledger.execute("b".repeat(64), command, extra) { "requested" } }
        clock = 100_000
        assertThrows(PhotoFolderScopeError::class.java) { ledger.execute("b".repeat(64), command, extra) { "requested" } }
    }

    @Test fun aFutureDatedCommandCannotOutliveTheNativeReplayFenceAndPromptTwice() {
        var elapsed = 100L
        var wall = now
        val ledger = NativeGalleryPermissionCommands(wallMs = { wall }) { elapsed }
        val future = JsonObject(message() + mapOf("created_ms" to JsonPrimitive(now + 300_000), "expires_ms" to JsonPrimitive(now + 360_000)))
        var prompts = 0
        fun attempt(at: Long) {
            wall = at
            try {
                val command = DeviceFileSourceCommand.parse(future, at)
                ledger.execute("b".repeat(64), command, future) { prompts++; "requested" }
            } catch (_: PhotoFolderScopeError) { /* Rejecting the command is safe. */ }
        }
        attempt(now)
        elapsed += 60_001
        attempt(now + 60_001)
        assertTrue("Future-dated source command prompted twice after its native replay fence expired", prompts <= 1)
    }

    @Test fun wallRollbackAfterPruningCannotReviveAnExpiredCommandOrRecoverTheLedger() {
        var elapsed = 100L; var wall = now
        val ledger = NativeGalleryPermissionCommands(wallMs = { wall }) { elapsed }
        val original = message(); var prompts = 0
        ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(original, wall), original) { prompts++; "requested" }
        elapsed += 60_001; wall += 60_001
        val fresh = JsonObject(message() + mapOf("created_ms" to JsonPrimitive(wall), "expires_ms" to JsonPrimitive(wall + 60_000)))
        ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(fresh, wall), fresh) { prompts++; "requested" }
        elapsed++; wall = now + 1_000
        assertThrows(PhotoFolderScopeError::class.java) {
            ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(original, wall), original) { prompts++; "requested" }
        }
        wall = now + 62_000
        assertThrows(PhotoFolderScopeError::class.java) {
            ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(fresh, wall), fresh) { prompts++; "requested" }
        }
        assertEquals(2, prompts)
    }

    @Test fun liveFutureCommandsHoldCapacityUntilBothReplayAndEnvelopeDeadlinesEnd() {
        var elapsed = 100L; var wall = now; var prompts = 0
        val ledger = NativeGalleryPermissionCommands(wallMs = { wall }) { elapsed }
        fun future() = JsonObject(message() + mapOf("created_ms" to JsonPrimitive(now + 300_000), "expires_ms" to JsonPrimitive(now + 360_000)))
        repeat(64) {
            val message = future()
            ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(message, wall), message) { prompts++; "requested" }
        }
        elapsed += 60_001; wall += 60_001
        val extra = future()
        assertThrows(PhotoFolderScopeError::class.java) {
            ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(extra, wall), extra) { prompts++; "requested" }
        }
        assertEquals(64, prompts)
        elapsed += 300_000; wall += 300_000
        val fresh = JsonObject(message() + mapOf("created_ms" to JsonPrimitive(wall), "expires_ms" to JsonPrimitive(wall + 60_000)))
        ledger.execute("b".repeat(64), DeviceFileSourceCommand.parse(fresh, wall), fresh) { prompts++; "requested" }
        assertEquals(65, prompts)
    }
}
