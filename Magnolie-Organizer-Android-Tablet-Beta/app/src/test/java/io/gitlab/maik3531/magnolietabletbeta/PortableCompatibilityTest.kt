package io.gitlab.maik3531.magnolietabletbeta

import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import java.util.Base64
import javax.crypto.spec.SecretKeySpec
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class PortableCompatibilityTest {
    private fun book()=JSONObject().put("version",6).put("termine",JSONArray()).put("aufgaben",JSONArray())
        .put("kontakte",JSONArray()).put("notizen",JSONArray()).put("einstellungen",JSONObject().put("regional",JSONObject()))
    @Test fun namedFactoryEnvelopeCanBeOpenedWithLegacyHmacDerivedKey() {
        val password="Synthetic ü😀 backup".toCharArray();val original=book().toString()
        try {
            val envelope=JSONObject(Portable.seal(original,password))
            assertEquals(210000,envelope.getInt("iterations"))
            val salt=Base64.getDecoder().decode(envelope.getString("salt"))
            val derived=Pbkdf2Sha256.deriveWithHmac(password,salt,210000)
            val crypto=DatenDateiKrypto({ SecretKeySpec(derived,"AES") })
            try { assertEquals(original,String(crypto.entschluesseln(Base64.getDecoder().decode(envelope.getString("ciphertext")),"tablet-export.json"),Charsets.UTF_8)) }
            finally { derived.fill(0) }
        } finally { password.fill('\u0000') }
    }
    @Test fun hmacDerivedLegacyEnvelopeUsesUnchangedFormatAndModernFactoryCanOpenIt() {
        val password="Synthetic legacy €😀".toCharArray();val original=book().toString()
        val salt=ByteArray(32) { it.toByte() };val derived=Pbkdf2Sha256.deriveWithHmac(password,salt,210000)
        try {
            val bytes=DatenDateiKrypto({ SecretKeySpec(derived,"AES") }).verschluesseln(original.toByteArray(),"tablet-export.json")
            val envelope=JSONObject().put("format","Magnolie-Organizer-Android-Tablet-Beta-1").put("iterations",210000)
                .put("salt",Base64.getEncoder().encodeToString(salt)).put("ciphertext",Base64.getEncoder().encodeToString(bytes)).toString()
            assertEquals(original,Portable.open(envelope,password))
            val tampered=JSONObject(envelope).put("iterations",209999).toString()
            try { Portable.open(tampered,password);fail("Changed KDF parameters accepted") } catch (_: IllegalArgumentException) { }
        } finally { derived.fill(0);password.fill('\u0000') }
    }
}
