package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class NativeGalleryRunCommandsTest {
    private val now = 1_800_000_000_000L
    private fun message() = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
        put("format", 1); put("operation", "run"); put("expected_version", "a".repeat(64))
        put("catalog_id", "11111111-1111-4111-8111-111111111111")
        put("album_id", "22222222-2222-4222-8222-222222222222"); put("desktop_choice", true)
    }, 60_000, now)
    private fun run(): NativeGallerySyncRun {
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        val request = NativeGalleryRequest(receiver, "a".repeat(64), setOf(GallerySourceKind.CAMERA))
        val album = GalleryAlbumCandidate(GallerySourceKind.CAMERA, "external", "bucket", "Camera", null, 1, false)
        val catalog = NativeGalleryAlbumCatalog(GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(album), request), Any(), { true })
        val page = catalog.page()
        return NativeGallerySyncRun(catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true), NativeGallerySourceRun())
    }

    @Test fun exactStartReplayReturnsTheNativeHandleWithoutLaunchingAgainButAnotherOwnerCannotAdoptIt() {
        val ledger = NativeGalleryRunCommands { 100 }; val owner = Any(); val message = message()
        val command = DeviceFileSourceCommand.parse(message, now); val native = run(); var calls = 0
        assertSame(native, ledger.start("b".repeat(64), owner, command, message) { calls++; native })
        assertSame(native, ledger.start("b".repeat(64), owner, command, message) { throw AssertionError("Repeated scan") })
        assertThrows(PhotoFolderScopeError::class.java) {
            ledger.start("b".repeat(64), Any(), command, message) { throw AssertionError("Reconnect scan") }
        }
        assertEquals(1, calls)
    }

    @Test fun changedCommandBytesCannotReuseAStartRequestId() {
        val ledger = NativeGalleryRunCommands { 100 }; val owner = Any(); val message = message()
        ledger.start("b".repeat(64), owner, DeviceFileSourceCommand.parse(message, now), message) { run() }
        val changed = JsonObject(message + ("body" to JsonObject(message["body"]!!.jsonObject + ("desktop_choice" to JsonPrimitive(false)))))
        assertThrows(PhotoFolderScopeError::class.java) {
            ledger.start("b".repeat(64), owner, DeviceFileSourceCommand.parse(changed, now), changed) { throw AssertionError("Mutated replay scan") }
        }
    }

    @Test fun nativeStartFailureIsHeldBeforeAnyRetryOrNewRuntime() {
        val ledger = NativeGalleryRunCommands { 100 }; val owner = Any(); val message = message()
        val command = DeviceFileSourceCommand.parse(message, now)
        assertThrows(java.io.IOException::class.java) { ledger.start("b".repeat(64), owner, command, message) { throw java.io.IOException("start failed") } }
        assertThrows(PhotoFolderScopeError::class.java) { ledger.start("b".repeat(64), owner, command, message) { throw AssertionError("Failure retried") } }
    }

    @Test fun boundedStartHistoryAndRollbackNeverEvictALiveReplayFence() {
        var clock = 100L; val ledger = NativeGalleryRunCommands { clock }; val owner = Any(); val native = run()
        repeat(64) { val message = message(); ledger.start("b".repeat(64), owner, DeviceFileSourceCommand.parse(message, now), message) { native } }
        val message = message(); val command = DeviceFileSourceCommand.parse(message, now)
        assertThrows(PhotoFolderScopeError::class.java) { ledger.start("b".repeat(64), owner, command, message) { throw AssertionError("Bound bypass") } }
        clock--
        assertThrows(PhotoFolderScopeError::class.java) { ledger.start("b".repeat(64), owner, command, message) { native } }
        clock = 100_000
        assertThrows(PhotoFolderScopeError::class.java) { ledger.start("b".repeat(64), owner, command, message) { native } }
    }

    @Test fun futureEnvelopeExpiryKeepsItsRunFenceBeyondSixtySecondsAndWallRollbackIsPermanent() {
        var elapsed = 100L; var wall = now
        val ledger = NativeGalleryRunCommands(wallMs = { wall }) { elapsed }
        val owner = Any(); val native = run(); var starts = 0
        val future = JsonObject(message() + mapOf("created_ms" to JsonPrimitive(now + 300_000), "expires_ms" to JsonPrimitive(now + 360_000)))
        ledger.start("b".repeat(64), owner, DeviceFileSourceCommand.parse(future, wall), future) { starts++; native }
        elapsed += 60_001; wall += 60_001
        assertSame(native, ledger.start("b".repeat(64), owner, DeviceFileSourceCommand.parse(future, wall), future) { starts++; native })
        elapsed++; wall--
        assertThrows(PhotoFolderScopeError::class.java) {
            ledger.start("b".repeat(64), owner, DeviceFileSourceCommand.parse(future, wall), future) { starts++; native }
        }
        wall += 2_000
        assertThrows(PhotoFolderScopeError::class.java) {
            ledger.start("b".repeat(64), owner, DeviceFileSourceCommand.parse(future, wall), future) { starts++; native }
        }
        assertEquals(1, starts)
    }
}
