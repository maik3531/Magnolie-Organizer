package io.gitlab.maik3531.magnolienotes.telefon

import java.security.MessageDigest
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import org.junit.Test

class PhoneWebcamMediaCodecTest {
    private fun codec(current: () -> Unit = {}) = PhoneWebcamMediaCodec("a".repeat(32), ByteArray(32) { it.toByte() }, current)
    private fun digest(value: ByteArray) = MessageDigest.getInstance("SHA-256").digest(value).joinToString("") { "%02x".format(it) }

    @Test fun binaryWireMatchesIndependentDesktopAudioThenVideoVectors() {
        codec().use { sender ->
            val audio = ByteArray(1920) { if (it % 2 == 0) 0x12 else 0x34 }
            val first = sender.encode(false, 0, 0, audio)
            assertEquals(1966, first.size)
            assertEquals("ac07c1baeaea58c00f70d794813f653e1409f865dc7363ecba9703612d0707e0", digest(first))
            assertContentEquals(audio, ByteArray(1920) { if (it % 2 == 0) 0x12 else 0x34 })
            val second = sender.encode(true, 0, 66667, ByteArray(460800))
            assertEquals(460846, second.size)
            assertEquals("8b253d9e1bf3129a3b7e3a1caa5aac9316cf9dc8a7348a71aca8e9c3f8ccaee3", digest(second))
        }
    }

    @Test fun invalidPayloadOrTimePermanentlyRetiresOriginalCodec() {
        for (scenario in listOf("size", "time", "sequence")) {
            codec().use { sender ->
                assertFailsWith<IllegalArgumentException> {
                    sender.encode(false, if (scenario == "sequence") -1 else 0,
                        if (scenario == "time") -1 else 0, ByteArray(if (scenario == "size") 1 else 1920))
                }
                assertFailsWith<IllegalStateException> { sender.encode(false, 0, 0, ByteArray(1920)) }
            }
        }
    }

    @Test fun revokedOriginalNativeContextNeverRevivesWhenBooleanReturns() {
        var allowed = true
        val sender = codec { check(allowed) { "original consent revoked" } }
        allowed = false
        assertFailsWith<IllegalStateException> { sender.encode(false, 0, 0, ByteArray(1920)) }
        allowed = true
        assertFailsWith<IllegalStateException> { sender.encode(false, 0, 0, ByteArray(1920)) }
        sender.close()
    }

    @Test fun revocationDuringEncryptionDiscardsResultAndRetiresNonceOwner() {
        var calls = 0
        val sender = codec { calls++; check(calls < 3) }
        assertFailsWith<IllegalStateException> { sender.encode(false, 0, 0, ByteArray(1920)) }
        assertFailsWith<IllegalStateException> { sender.encode(false, 0, 0, ByteArray(1920)) }
        sender.close()
    }

    @Test fun explicitStopAndMalformedContextCannotBeUsedAsCapturePermission() {
        val sender = codec(); sender.close()
        assertFailsWith<IllegalStateException> { sender.encode(false, 0, 0, ByteArray(1920)) }
        assertFailsWith<IllegalArgumentException> { PhoneWebcamMediaCodec("not-an-id", ByteArray(32)) {} }
        assertFailsWith<IllegalArgumentException> { PhoneWebcamMediaCodec("a".repeat(32), ByteArray(31)) {} }
    }
}
