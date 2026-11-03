package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.security.MessageDigest

class NativeImageAnimationTest {
    private fun hex(value: String) = value.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    internal fun gif(frames: Int = 1): ByteArray {
        val header = hex("47494638396101000100800000000000ffffff")
        val image = hex("2c0000000001000100000202440100")
        return header + (0 until frames).fold(ByteArray(0)) { data, _ -> data + image } + byteArrayOf(0x3B)
    }
    private fun manifest(data: ByteArray, path: String = "not-an-extension-hint.bin") = DeviceFileManifest.parse(buildJsonObject {
        put("format", 1); put("transfer_id", "1".repeat(32)); put("source_id", "2".repeat(32))
        put("sender_id", "sender_fixture_01"); put("receiver_id", "receiver_fixture_01")
        put("chunk_bytes", DeviceFileManifest.CHUNK_BYTES); put("total_bytes", data.size)
        put("files", JsonArray(listOf(buildJsonObject {
            put("id", "3".repeat(32)); put("path", path); put("size", data.size)
            put("sha256", MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it.toInt() and 255) })
        })))
    })
    private fun inspect(data: ByteArray, path: String = "arbitrary.bin") = NativeImageAnimation.inspect(manifest(data, path), "3".repeat(32)) { index ->
        data.copyOfRange(index * DeviceFileManifest.CHUNK_BYTES, minOf(data.size, (index + 1) * DeviceFileManifest.CHUNK_BYTES))
    }

    @Test fun actualContainerFramesNotFilenameSelectStillOrAnimated() {
        assertEquals(NativeImageAnimationKind.STILL, inspect(gif(), "claims-animated.gif").kind)
        val observed = inspect(gif(2), "unrelated.jpg")
        assertEquals(NativeImageAnimationKind.ANIMATED, observed.kind)
        assertEquals(manifest(gif(2), "unrelated.jpg").fingerprint, observed.manifestSha256)
        assertFalse(observed.grantsWriteAuthority); assertFalse(observed.isSavedReceipt)
        assertEquals(NativeImageAnimationKind.UNKNOWN, inspect("not a GIF".toByteArray(), "animated.gif").kind)
    }

    @Test fun imageMarkersInsideCommentSubBlocksDoNotManufactureAnotherFrame() {
        val source = gif()
        val comment = byteArrayOf(0x21, 0xFE.toByte(), 3, 0x2C, 0x2C, 0x2C, 0)
        assertEquals(NativeImageAnimationKind.STILL, inspect(source.dropLast(1).toByteArray() + comment + byteArrayOf(0x3B)).kind)
    }

    @Test fun truncatedMalformedOrTrailingContainersRemainUnknown() {
        val source = gif(2)
        for (end in source.indices) assertEquals("truncated at $end", NativeImageAnimationKind.UNKNOWN, inspect(source.copyOf(end)).kind)
        assertEquals(NativeImageAnimationKind.UNKNOWN, inspect(source + byteArrayOf(0)).kind)
        assertEquals(NativeImageAnimationKind.UNKNOWN, inspect(gif(0)).kind)
        val wrongCodeSize = gif(); wrongCodeSize[29] = 12
        assertEquals(NativeImageAnimationKind.UNKNOWN, inspect(wrongCodeSize).kind)
    }

    @Test fun fullByteHashAndExactChunkSizesAreRequiredEvenForUnknownFormats() {
        val data = gif(2); val manifest = manifest(data)
        assertThrows(PhotoFolderScopeError::class.java) {
            NativeImageAnimation.inspect(manifest, "3".repeat(32)) { data.copyOf().also { it[0] = 0 } }
        }
        assertThrows(PhotoFolderScopeError::class.java) { NativeImageAnimation.inspect(manifest, "3".repeat(32)) { data.copyOf(data.size - 1) } }
        assertThrows(PhotoFolderScopeError::class.java) { NativeImageAnimation.inspect(manifest, "f".repeat(32)) { data.copyOf() } }
    }

    @Test fun providerReadFailureIsNotDowngradedToUnknownAndAllReturnedPlaintextIsCleared() {
        val data = gif(2); val supplied = mutableListOf<ByteArray>()
        NativeImageAnimation.inspect(manifest(data), "3".repeat(32)) { data.copyOf().also { supplied += it } }
        assertTrue(supplied.isNotEmpty()); assertTrue(supplied.all { part -> part.all { it == 0.toByte() } })
        assertThrows(java.io.IOException::class.java) {
            NativeImageAnimation.inspect(manifest(data), "3".repeat(32)) { throw java.io.IOException("native read revoked") }
        }
    }

    @Test fun boundedChunkReaderParsesFramesAcrossChunkBoundaryWithoutWholeFileBuffer() {
        val prefix = gif().dropLast(1).toByteArray()
        val comments = (0 until 260).fold(ByteArray(0)) { bytes, _ -> bytes + byteArrayOf(0x21, 0xFE.toByte(), 255.toByte()) + ByteArray(255) { 0x2C } + byteArrayOf(0) }
        val image = hex("2c0000000001000100000202440100")
        assertEquals(NativeImageAnimationKind.ANIMATED, inspect(prefix + comments + image + byteArrayOf(0x3B)).kind)
    }
}
