package io.gitlab.maik3531.magnolienotes.sicherung

import javax.crypto.AEADBadTagException
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Test

class PasswortHuelleTest {
    private fun key(): SecretKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    @Test fun `jede Huelle erhaelt einen frischen Nonce`() {
        val key = key()
        val eins = PasswortHuelle.verschluesseln("geheim".toCharArray(), key)
        val zwei = PasswortHuelle.verschluesseln("geheim".toCharArray(), key)
        assertFalse(eins.contentEquals(zwei))
        assertArrayEquals("geheim".toCharArray(), PasswortHuelle.entschluesseln(eins, key))
        assertArrayEquals("geheim".toCharArray(), PasswortHuelle.entschluesseln(zwei, key))
    }

    @Test fun `Manipulation wird authentifiziert abgewiesen`() {
        val key = key()
        val huelle = PasswortHuelle.verschluesseln("nicht gespeichert".toCharArray(), key)
        huelle[huelle.lastIndex] = (huelle.last().toInt() xor 1).toByte()
        assertThrows(AEADBadTagException::class.java) { PasswortHuelle.entschluesseln(huelle, key) }
    }

    @Test fun `fehlender Schluessel wird bei bestehender Huelle nie ersetzt`() {
        var angelegt = false
        val quelle = object : AutoSicherungsSchluessel {
            override fun vorhandener(): SecretKey? = null
            override fun anlegen(): SecretKey { angelegt = true; return key() }
        }
        assertThrows(AutoSicherungsSchluesselFehlt::class.java) {
            PasswortHuelle.sichern("neu".toCharArray(), byteArrayOf(1), quelle)
        }
        assertFalse(angelegt)
        assertThrows(AutoSicherungsSchluesselFehlt::class.java) {
            PasswortHuelle.laden(byteArrayOf(1), quelle)
        }
        assertFalse(angelegt)
    }
}
