package io.gitlab.maik3531.magnolietabletbeta

import java.nio.CharBuffer
import java.nio.charset.CodingErrorAction
import java.security.NoSuchAlgorithmException
import javax.crypto.Mac
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/** Same RFC 8018 PBKDF2-HMAC-SHA256/256-bit key on systems without the named
 * PBKDF2 factory (Android's platform factory starts at API 26). No weaker KDF
 * and no third-party JCA provider is selected. The platform HmacSHA256 primitive
 * is also used by the account revision fence on every supported Android version.
 */
internal object Pbkdf2Sha256 {
    fun derive(password: CharArray, salt: ByteArray, iterations: Int): ByteArray {
        val spec=PBEKeySpec(password,salt,iterations,256)
        return try {
            try { SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded }
            catch (_: NoSuchAlgorithmException) { deriveWithHmac(password,salt,iterations) }
        } finally { spec.clearPassword() }
    }
    /** One output block: hLen = dkLen = 32 bytes. Kept independently testable
     * against the named JCA factory and published SHA-256 PBKDF2 vectors. */
    fun deriveWithHmac(password: CharArray, salt: ByteArray, iterations: Int): ByteArray {
        require(password.isNotEmpty() && salt.isNotEmpty() && iterations > 0)
        val encoded=Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPLACE)
            .onUnmappableCharacter(CodingErrorAction.REPLACE).encode(CharBuffer.wrap(password))
        val secret=ByteArray(encoded.remaining()).also { encoded.get(it) }
        if(encoded.hasArray()) encoded.array().fill(0)
        val input=salt.copyOf(salt.size+4).also { it[it.lastIndex]=1 }
        var previous: ByteArray?=null
        var derived: ByteArray?=null
        var complete=false
        try {
            val mac=Mac.getInstance("HmacSHA256")
            mac.init(SecretKeySpec(secret,"HmacSHA256"))
            var u=mac.doFinal(input);previous=u
            val output=u.copyOf();derived=output
            repeat(iterations-1) {
                val next=mac.doFinal(u);u.fill(0);u=next;previous=u
                for(index in output.indices) output[index]=(output[index].toInt() xor u[index].toInt()).toByte()
            }
            complete=true;return output
        } finally {
            secret.fill(0);input.fill(0);previous?.fill(0)
            if(!complete) derived?.fill(0)
        }
    }
}
