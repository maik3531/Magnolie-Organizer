package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

class Pbkdf2Sha256Test {
    private fun hex(bytes: ByteArray)=bytes.joinToString("") { "%02x".format(it.toInt() and 255) }
    @Test fun fallbackMatchesPublishedPbkdf2HmacSha256Vectors() {
        for((count,expected) in listOf(
            1 to "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b",
            2 to "ae4d0c95af6b46d32d0adff928f06dd02a303f8ef3c251dfd6e2d85a95474c43",
            4096 to "c5e478d59288c841aa530db6845c4c8d962893a001ce4e11a4963873aa98134a")) {
            assertEquals(expected,hex(Pbkdf2Sha256.deriveWithHmac("password".toCharArray(),"salt".toByteArray(),count)))
        }
    }
    @Test fun utf8NulSupplementaryAndMalformedCharactersMatchNamedFactory() {
        for(password in listOf("plain password","äöü密码नमस्ते😀","nul\u0000password","unpaired\uD800end")) {
            val chars=password.toCharArray();val salt=ByteArray(32) { it.toByte() }
            val spec=PBEKeySpec(chars,salt,2048,256)
            try {
                val named=SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
                assertArrayEquals(named,Pbkdf2Sha256.deriveWithHmac(chars,salt,2048))
                assertArrayEquals(named,Pbkdf2Sha256.derive(chars,salt,2048))
                assertArrayEquals(password.toCharArray(),chars)
            } finally { spec.clearPassword();chars.fill('\u0000') }
        }
    }
    @Test fun existingEnvelopeKeyParametersRemainExactlyCompatible() {
        val password="Synthetic recovery ä😀".toCharArray();val salt=ByteArray(32) { (31-it).toByte() }
        val spec=PBEKeySpec(password,salt,210000,256)
        try { assertArrayEquals(SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded,
            Pbkdf2Sha256.deriveWithHmac(password,salt,210000)) }
        finally { spec.clearPassword();password.fill('\u0000') }
    }
}
