package io.gitlab.maik3531.magnolienotes.sicherung

import org.junit.Assert.*
import org.junit.Test
import java.security.*
import java.security.spec.AlgorithmParameterSpec
import javax.crypto.*
import javax.crypto.spec.SecretKeySpec

/** A non-exportable test key enforces the Keystore IV contract without accessing Android keys. */
class KeystorePasswortRegressionTest {
    private class TestKey : SecretKey {
        override fun getAlgorithm() = "AES"
        override fun getFormat(): String? = null
        override fun getEncoded(): ByteArray? = null
    }

    class KeystoreCipher : CipherSpi() {
        private val delegate = Cipher.getInstance("AES/GCM/NoPadding", "SunJCE")
        override fun engineSetMode(mode: String) {}
        override fun engineSetPadding(padding: String) {}
        override fun engineGetBlockSize() = delegate.blockSize
        override fun engineGetOutputSize(inputLen: Int) = delegate.getOutputSize(inputLen)
        override fun engineGetIV(): ByteArray = delegate.iv
        override fun engineGetParameters(): AlgorithmParameters = delegate.parameters
        override fun engineInit(opmode: Int, key: Key, random: SecureRandom?) {
            require(key is TestKey)
            delegate.init(opmode, SecretKeySpec(ByteArray(32), "AES"), random)
        }
        override fun engineInit(opmode: Int, key: Key, params: AlgorithmParameterSpec?, random: SecureRandom?) {
            if (opmode == Cipher.ENCRYPT_MODE && params != null)
                throw InvalidAlgorithmParameterException("Caller-provided IV not permitted")
            require(key is TestKey)
            delegate.init(opmode, SecretKeySpec(ByteArray(32), "AES"), params, random)
        }
        override fun engineInit(opmode: Int, key: Key, params: AlgorithmParameters?, random: SecureRandom?) {
            throw InvalidAlgorithmParameterException("Unused test API")
        }
        override fun engineUpdateAAD(src: ByteArray, offset: Int, len: Int) = delegate.updateAAD(src, offset, len)
        override fun engineUpdate(input: ByteArray, inputOffset: Int, inputLen: Int): ByteArray? =
            delegate.update(input, inputOffset, inputLen)
        override fun engineUpdate(input: ByteArray, inputOffset: Int, inputLen: Int, output: ByteArray, outputOffset: Int) =
            delegate.update(input, inputOffset, inputLen, output, outputOffset)
        override fun engineDoFinal(input: ByteArray, inputOffset: Int, inputLen: Int): ByteArray =
            delegate.doFinal(input, inputOffset, inputLen)
        override fun engineDoFinal(input: ByteArray, inputOffset: Int, inputLen: Int, output: ByteArray, outputOffset: Int) =
            delegate.doFinal(input, inputOffset, inputLen, output, outputOffset)
    }

    @Test fun `F19 password wrapping requests provider IV and preserves the existing envelope format`() {
        val provider = object : Provider("MagnolieTestKeystore", 1.0, "Synthetic test provider") {
            init { put("Cipher.AES/GCM/NoPadding", KeystoreCipher::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        try {
            val password = "do not lose this password".toCharArray()
            val first = PasswortHuelle.verschluesseln(password, TestKey())
            val second = PasswortHuelle.verschluesseln(password, TestKey())
            assertFalse(first.contentEquals(second))
            assertArrayEquals(password, PasswortHuelle.entschluesseln(first, TestKey()))
            assertArrayEquals(password, PasswortHuelle.entschluesseln(second, TestKey()))
            first[first.lastIndex] = (first.last().toInt() xor 1).toByte()
            assertThrows(AEADBadTagException::class.java) { PasswortHuelle.entschluesseln(first, TestKey()) }
        } finally { Security.removeProvider(provider.name) }
    }
}
