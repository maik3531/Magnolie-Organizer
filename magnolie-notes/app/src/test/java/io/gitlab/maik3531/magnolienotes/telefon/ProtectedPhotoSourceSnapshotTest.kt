package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.os.CancellationSignal
import android.os.OperationCanceledException
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.io.InputStream
import java.nio.file.Files
import java.security.MessageDigest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class ProtectedPhotoSourceSnapshotTest {
    private class Fixture(data: ByteArray) : AutoCloseable {
        val native = AndroidPhotoFolderInventoryTest.Fixture()
        val parent = Files.createTempDirectory(File("/tmp/opencode").toPath(), "photo-freeze329-").toFile()
        val root = Files.createDirectory(File(parent, "reserved-private-snapshot").toPath(),
            java.nio.file.attribute.PosixFilePermissions.asFileAttribute(java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"))).toFile()
        val original = File(parent, "original-photo-fixture").apply { writeBytes(data) }
        val documentId = "selected/photo"
        var key: SecretKey? = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        val protection = DeviceTransferProtection.fromExistingKeyReader { key }
        val reader = AndroidPhotoSourceReader(native.context, native.scope)
        val cancellation = CancellationSignal()
        init {
            native.provider.rows["selected"] = listOf(AndroidPhotoFolderInventoryTest.Row(documentId, size = data.size.toLong()))
            native.provider.contents[documentId] = original
        }
        fun inventory() = native.scan()
        fun freeze(inventory: PhotoFolderInventory = inventory(), source: PhotoSourceAccess = reader, boundary: (String) -> Unit = {}) = ProtectedPhotoSourceSnapshot.freeze(
            root, inventory, "sender_fixture_01", native.scope, source, protection, cancellation, boundary)
        override fun close() { parent.deleteRecursively() }
    }

    @Test fun safReaderNeverAdoptsAGalleryGenerationRevisionAsASafProviderProof() {
        Fixture("hello".toByteArray()).use { f ->
            val inventory = f.inventory(); val opened = f.native.provider.opened
            val entry = inventory.entries.single().copy(nativeRevision = "9")
            assertEquals("photo_snapshot_unsupported_native_revision", assertThrows(PhotoFolderScopeError::class.java) {
                f.reader.openRead(inventory.lease, entry, CancellationSignal()) }.code)
            assertEquals(opened, f.native.provider.opened)
        }
    }

    @Test fun actualPfdBytesAreFrozenEncryptedReadBackAndNeverReplacedByLaterLiveContent() {
        val data = ByteArray(DeviceFileManifest.CHUNK_BYTES + 7) { (it % 251).toByte() }
        Fixture(data).use { f ->
            val snapshot = f.freeze()
            val member = snapshot.manifest.files.single()
            val legacy = f.native.lease
            val legacyContext = JsonObject(mapOf("tree" to JsonPrimitive(legacy.preference.treeUri),
                "source_version" to JsonPrimitive(legacy.version), "source_epoch" to JsonPrimitive(legacy.preference.epoch),
                "receiver" to JsonPrimitive(legacy.preference.receiverId), "receiver_identity" to JsonPrimitive(legacy.preference.receiverIdentitySha256),
                "read_grant" to JsonPrimitive(legacy.readGrantToken), "permission_epoch" to JsonPrimitive(legacy.receiver.permissionEpoch)))
            val expectedDomain = MessageDigest.getInstance("SHA-256").digest(TelefonKanonisch.bytes(legacyContext))
                .joinToString("") { "%02x".format(java.util.Locale.ROOT, it.toInt() and 255) }
            assertEquals(JsonPrimitive(expectedDomain), snapshot.nativeRecord()["source_domain"])
            val expected = MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it.toInt() and 255) }
            assertEquals(expected, member.sha256); assertEquals(data.size.toLong(), member.size)
            assertEquals(2, f.native.provider.opened) // Both bounded source observations used actual read-only PFDs.
            assertEquals(0, f.native.provider.deleted)
            assertArrayEquals(data, snapshot.readChunk(member.id, 0) + snapshot.readChunk(member.id, 1))
            assertTrue(f.root.listFiles()!!.all { it.extension == "enc" })
            assertTrue(f.root.listFiles()!!.none { it.readBytes().toString(Charsets.ISO_8859_1).contains("photo.jpg") })
            f.original.writeBytes(ByteArray(data.size) { 42 })
            assertArrayEquals(data, snapshot.readChunk(member.id, 0) + snapshot.readChunk(member.id, 1))
            snapshot.discard()
            assertFalse(f.root.exists()); assertArrayEquals(ByteArray(data.size) { 42 }, f.original.readBytes())
        }
    }

    @Test fun zeroBytesStillRequireTwoActualSourceOpensAndAnOwnedEncryptedMarker() {
        Fixture(byteArrayOf()).use { f ->
            val snapshot = f.freeze()
            assertEquals(0L, snapshot.manifest.totalBytes); assertEquals(2, f.native.provider.opened)
            val empty = f.root.listFiles()!!.single { it.name.startsWith("empty-") }
            assertTrue(empty.length() > 0)
            snapshot.discard(); assertFalse(f.root.exists())
        }
    }

    @Test fun changedSameSizeSourceBetweenPassesDoesNotCreateASealedManifestOrOverwriteTheSource() {
        Fixture("hello".toByteArray()).use { f ->
            f.native.provider.onOpen = { _, count -> if (count == 2) f.original.writeText("other") }
            val failure = assertThrows(PhotoSnapshotBuildFailure::class.java) { f.freeze() }
            assertEquals("photo_snapshot_live_source_changed", (failure.cause as PhotoFolderScopeError).code)
            assertThrows(PhotoFolderScopeError::class.java) { failure.pending.manifest }
            assertEquals("other", f.original.readText())
            failure.pending.discard(); assertFalse(f.root.exists())
        }
    }

    @Test fun staleMetadataExtraBytesAndTruncationCannotBecomeFrozenSourceProofs() {
        for (changed in listOf("tiny", "hello-extra")) Fixture("hello".toByteArray()).use { f ->
            f.original.writeText(changed)
            val failure = assertThrows(PhotoSnapshotBuildFailure::class.java) { f.freeze() }
            assertEquals(if (changed.length < 5) "photo_snapshot_live_source_truncated" else "photo_snapshot_live_source_grew",
                (failure.cause as PhotoFolderScopeError).code)
            assertFalse(File(f.root, "manifest.enc").exists())
            failure.pending.discard()
        }
        Fixture("hello".toByteArray()).use { f ->
            val inventory = f.inventory()
            f.native.provider.rows["selected"] = listOf(AndroidPhotoFolderInventoryTest.Row(f.documentId, "changed.jpg"))
            val failure = assertThrows(PhotoSnapshotBuildFailure::class.java) { f.freeze(inventory) }
            assertEquals("photo_snapshot_metadata_changed", (failure.cause as PhotoFolderScopeError).code)
            assertEquals(0, f.native.provider.opened)
            failure.pending.discard()
        }
    }

    @Test fun nativeScopeRevocationOrCancellationDuringOpenPreventsCompletionAndStillAllowsOwnedCleanup() {
        for (cancel in listOf(false, true)) Fixture("hello".toByteArray()).use { f ->
            f.native.provider.onOpen = { _, _ ->
                if (cancel) f.cancellation.cancel() else f.native.receiver = f.native.receiver.copy(permissionEpoch = "a".repeat(64))
            }
            val failure = assertThrows(PhotoSnapshotBuildFailure::class.java) { f.freeze() }
            if (cancel) assertTrue(failure.cause is OperationCanceledException)
            else assertEquals("photo_snapshot_source_revoked", (failure.cause as PhotoFolderScopeError).code)
            assertFalse(File(f.root, "manifest.enc").exists())
            failure.pending.discard(); assertFalse(f.root.exists())
        }
    }

    @Test fun originalCiphertextAndUnknownFilesArePreservedInsteadOfBeingRebaselinedOrRecursivelyDeleted() {
        Fixture("hello".toByteArray()).use { f ->
            val snapshot = f.freeze(); val member = snapshot.manifest.files.single()
            val chunk = File(f.root, "${member.id}-0.enc"); val original = chunk.readBytes()
            val changed = original.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }
            chunk.writeBytes(changed)
            assertThrows(PhotoFolderScopeError::class.java) { snapshot.readChunk(member.id, 0) }
            assertThrows(PhotoFolderScopeError::class.java) { snapshot.discard() }
            assertArrayEquals(changed, chunk.readBytes()); assertTrue(File(f.root, "owner.enc").exists())
            chunk.writeBytes(original) // Restore only exact injected fixture bytes, never product user data.
            val unknown = File(f.root, "unfamiliar-work").apply { writeText("keep") }
            assertThrows(PhotoFolderScopeError::class.java) { snapshot.discard() }
            assertEquals("keep", unknown.readText()); assertTrue(File(f.root, "owner.enc").exists())
            unknown.delete(); snapshot.discard()
        }
    }

    @Test fun missingExistingKeyDoesNotGenerateAnotherKeyOrTouchTheLivePhoto() {
        Fixture("hello".toByteArray()).use { f ->
            f.key = null
            val failure = assertThrows(PhotoSnapshotBuildFailure::class.java) { f.freeze() }
            assertTrue(failure.cause is DeviceTransferKeyUnavailable); assertNull(f.key)
            assertEquals("hello", f.original.readText()); assertEquals(0, f.native.provider.opened)
            failure.pending.discard()
        }
    }

    @Test fun stalledStreamsCannotAcquireACompleteSnapshot() {
        Fixture("hello".toByteArray()).use { f ->
            val source = object : PhotoSourceAccess {
                override fun verifyMetadata(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal) { }
                override fun openRead(lease: NativePhotoSourceLease, entry: PhotoInventoryEntry, cancellation: CancellationSignal) = object : InputStream() {
                    override fun read() = 0
                    override fun read(buffer: ByteArray, offset: Int, length: Int) = 0
                }
            }
            val failure = assertThrows(PhotoSnapshotBuildFailure::class.java) { f.freeze(source = source) }
            assertEquals("photo_snapshot_stalled_source", (failure.cause as PhotoFolderScopeError).code)
            failure.pending.discard()
        }
    }

    @Test fun changedRootOwnerOrLinkedCipherNeverRedirectsAReadOrCleanupToForeignBytes() {
        for (kind in listOf("directory", "owner", "symlink", "hardlink")) Fixture("hello".toByteArray()).use { f ->
            val snapshot = f.freeze(); val member = snapshot.manifest.files.single()
            val chunk = File(f.root, "${member.id}-0.enc")
            val heldRoot = File(f.parent, "held-snapshot-root")
            val heldChunk = File(f.parent, "held-own-cipher")
            val foreign = File(f.parent, "foreign-fixture").apply { writeText("foreign bytes stay") }
            Files.setPosixFilePermissions(foreign.toPath(), java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"))
            val owner = File(f.root, "owner.enc"); val originalOwner = owner.readBytes()
            when (kind) {
                "directory" -> { assertTrue(f.root.renameTo(heldRoot)); assertTrue(f.root.mkdir()) }
                "owner" -> owner.writeBytes(originalOwner.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
                else -> {
                    assertTrue(chunk.renameTo(heldChunk))
                    if (kind == "symlink") Files.createSymbolicLink(chunk.toPath(), foreign.toPath())
                    else Files.createLink(chunk.toPath(), foreign.toPath())
                }
            }
            assertThrows(PhotoFolderScopeError::class.java) { snapshot.readChunk(member.id, 0) }
            assertThrows(PhotoFolderScopeError::class.java) { snapshot.discard() }
            assertEquals("foreign bytes stay", foreign.readText())
            // Restore only this test's exact known objects; real failed witnesses are never auto-repaired.
            when (kind) {
                "directory" -> { assertTrue(f.root.delete()); assertTrue(heldRoot.renameTo(f.root)) }
                "owner" -> owner.writeBytes(originalOwner)
                else -> { assertTrue(chunk.delete()); assertTrue(heldChunk.renameTo(chunk)) }
            }
            snapshot.discard(); assertEquals("foreign bytes stay", foreign.readText())
        }
    }

    @Test fun partialExactCleanupRetainsKnownProgressAndCanRetryWithoutAdoptingNewBaselines() {
        Fixture("hello".toByteArray()).use { f ->
            var fail = true
            val snapshot = f.freeze(boundary = {
                if (fail && it == "discarded-entry") { fail = false; throw java.io.IOException("synthetic cleanup interruption") }
            })
            assertThrows(java.io.IOException::class.java) { snapshot.discard() }
            assertTrue(File(f.root, "owner.enc").exists())
            assertThrows(PhotoFolderScopeError::class.java) { snapshot.manifest }
            snapshot.discard()
            assertFalse(f.root.exists()); assertEquals("hello", f.original.readText())
        }
    }
}
