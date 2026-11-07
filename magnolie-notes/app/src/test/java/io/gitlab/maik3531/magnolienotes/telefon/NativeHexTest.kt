package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.*
import org.junit.Test
import java.security.MessageDigest
import java.util.Locale

class NativeHexTest {
    private fun previous(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }

    @Test fun actualControlDigestPreservesDomainsAndCanonicalPayloadBytes() {
        val values = listOf(kotlinx.serialization.json.JsonNull,
            kotlinx.serialization.json.JsonPrimitive("ä\u0000雪"),
            kotlinx.serialization.json.JsonObject(mapOf("z" to kotlinx.serialization.json.JsonPrimitive(true),
                "a" to kotlinx.serialization.json.JsonPrimitive(398))))
        for (domain in listOf("", "magnolie-file-permission-v1\u0000", "magnolie-file-control-v1\u0000")) {
            for (value in values) {
                val expected = previous(MessageDigest.getInstance("SHA-256")
                    .digest(domain.toByteArray(Charsets.UTF_8) + TelefonKanonisch.bytes(value)))
                assertEquals(expected, DeviceFileControl.digest(domain, value))
            }
        }
    }

    @Test fun everyByteAndEmptyInputRemainExactlyThePreviousCanonicalLowercaseHex() {
        assertEquals("", NativeHex.lower(byteArrayOf()))
        val bytes = ByteArray(256) { it.toByte() }
        assertEquals(previous(bytes), NativeHex.lower(bytes))
        assertEquals(512, NativeHex.lower(bytes).length)
        for (value in 0..255) assertEquals(previous(byteArrayOf(value.toByte())), NativeHex.lower(byteArrayOf(value.toByte())))
    }

    @Test fun sha256KnownVectorsAndDeterministicArbitraryPayloadsPreserveExactDigests() {
        fun digest(bytes: ByteArray) = NativeHex.lower(MessageDigest.getInstance("SHA-256").digest(bytes))
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", digest(byteArrayOf()))
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", digest("abc".toByteArray()))
        val random = java.util.Random(398)
        for (size in listOf(1, 31, 32, 255, 4096)) {
            val bytes = ByteArray(size).also(random::nextBytes)
            assertEquals(previous(bytes), NativeHex.lower(bytes))
            val hash = MessageDigest.getInstance("SHA-256").digest(bytes)
            assertEquals(previous(hash), NativeHex.lower(hash))
        }
    }

    @Test fun renderingDoesNotDependOnLocaleOrChangeTheInputBytes() {
        val bytes = byteArrayOf(0, 1, 15, 16, 127, 128.toByte(), 255.toByte()); val original = bytes.copyOf()
        val locale = Locale.getDefault()
        try {
            for (language in listOf("ar", "tr", "de")) {
                Locale.setDefault(Locale.forLanguageTag(language))
                assertEquals("00010f107f80ff", NativeHex.lower(bytes)); assertArrayEquals(original, bytes)
            }
        } finally { Locale.setDefault(locale) }
    }
}
