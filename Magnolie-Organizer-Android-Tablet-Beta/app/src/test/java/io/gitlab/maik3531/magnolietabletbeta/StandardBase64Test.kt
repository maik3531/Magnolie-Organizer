package io.gitlab.maik3531.magnolietabletbeta

import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.Base64
import java.util.Random
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

class StandardBase64Test {
    private fun reference(text: String): ByteArray? = try { Base64.getDecoder().decode(text) } catch (_: IllegalArgumentException) { null }
    private fun actual(text: String): ByteArray? = try { StandardBase64.decode(text) } catch (_: IllegalArgumentException) { null }
    private fun equivalent(text: String) {
        val expected = reference(text); val decoded = actual(text)
        if (expected == null) assertNull("A malformed Basic encoding was accepted", decoded)
        else { assertNotNull("A valid Basic encoding was rejected", decoded); assertArrayEquals(expected, decoded) }
    }
    @Test fun RFC4648AndArbitraryBinaryUseExactlyTheExistingJDKEncoding() {
        for ((plain, encoded) in listOf("" to "", "f" to "Zg==", "fo" to "Zm8=", "foo" to "Zm9v", "foob" to "Zm9vYg==", "fooba" to "Zm9vYmE=", "foobar" to "Zm9vYmFy")) {
            assertEquals(encoded, StandardBase64.encode(plain.toByteArray())); assertArrayEquals(plain.toByteArray(), StandardBase64.decode(encoded))
        }
        val random = Random(8122026L)
        for (length in 0..1024) {
            val bytes = ByteArray(length).also(random::nextBytes)
            val encoded = StandardBase64.encode(bytes)
            assertEquals(Base64.getEncoder().encodeToString(bytes), encoded)
            assertArrayEquals(bytes, StandardBase64.decode(encoded)); equivalent(encoded.trimEnd('='))
        }
        val unicode = "üser:pássword 💐".toByteArray(Charsets.UTF_8)
        assertEquals(Base64.getEncoder().encodeToString(unicode), StandardBase64.encode(unicode))
    }
    @Test fun paddedUnpaddedAndTerminalBitsPreserveBasicDecoderSemantics() {
        val alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        for (last in alphabet) for (text in listOf("A$last", "A$last==", "AA$last", "AA$last=", "AAA$last")) equivalent(text)
        for (text in listOf("A", "=", "==", "===", "====", "A=", "A===", "AA=", "AAA==", "AAAA=", "AAAA==", "AA==A", "AA=A", "AA==\n", "AA-", "AA_", " A A ", "\r\n", "AA\t", "éA", "A\u0000", "A\ud800", "A💐")) equivalent(text)
    }
    @Test fun deterministicPropertiesRejectEveryIgnoredWhitespaceUnicodeAndURLCharacter() {
        val random = Random(72385L)
        val alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/= -_\t\r\né\u0000\ud800"
        repeat(6000) {
            val length = random.nextInt(65)
            equivalent(buildString { repeat(length) { append(alphabet[random.nextInt(alphabet.length)]) } })
        }
        for (code in 0..255) {
            equivalent("AA" + code.toChar() + "A")
            equivalent("AA==" + code.toChar())
        }
    }
    @Test fun unchangedPortableCryptoCrossDecryptsWithIndependentJDKBase64BothDirections() {
        val plain = JSONObject().put("version", 6).put("termine", JSONArray()).put("aufgaben", JSONArray())
            .put("kontakte", JSONArray()).put("notizen", JSONArray()).put("einstellungen", JSONObject().put("regional", JSONObject().put("language", "en"))).toString()
        for (passwordText in listOf("synthetic-password-123", "synthetic-pässword-456")) {
            val password = passwordText.toCharArray()
            try {
                val sealed = JSONObject(Portable.seal(plain, password))
                val salt = Base64.getDecoder().decode(sealed.getString("salt"))
                val specification = PBEKeySpec(password, salt, 210000, 256)
                val material = try { SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(specification).encoded } finally { specification.clearPassword() }
                val key = try { SecretKeySpec(material, "AES") } finally { material.fill(0) }
                val crypto = DatenDateiKrypto({ key })
                val decrypted = crypto.entschluesseln(Base64.getDecoder().decode(sealed.getString("ciphertext")), "tablet-export.json")
                assertEquals(plain, decrypted.toString(Charsets.UTF_8))
                val legacy = JSONObject(sealed.toString()).put("ciphertext", Base64.getEncoder().encodeToString(crypto.verschluesseln(plain.toByteArray(), "tablet-export.json")))
                assertEquals(plain, Portable.open(legacy.toString(), password))
            } finally { password.fill('\u0000') }
        }
    }
}
