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
}
