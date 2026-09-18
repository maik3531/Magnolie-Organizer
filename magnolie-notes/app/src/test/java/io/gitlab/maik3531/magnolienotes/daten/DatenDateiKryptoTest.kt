package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.nio.file.Files
import javax.crypto.AEADBadTagException
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

class DatenDateiKryptoTest {
    @Test fun `format hat kennung frische iv und authentifizierte metadaten`() {
        val crypto = DatenDateiKrypto(::keyA)
        val klar = "{\"attachment\":\"data:image/png;base64,geheim\"}".toByteArray()
        val eins = crypto.verschluesseln(klar, "notizen.json")
        val zwei = crypto.verschluesseln(klar, "notizen.json")
        assertTrue(crypto.istVerschluesselt(eins))
        assertFalse(eins.contentEquals(zwei))
        assertArrayEquals(klar, crypto.entschluesseln(eins, "notizen.json"))
        erwarteFehler { crypto.entschluesseln(eins, "baum.json") }
    }

    @Test fun `manipulation und falscher schluessel werden abgelehnt`() {
        val original = DatenDateiKrypto(::keyA).verschluesseln("privater-x25519-schluessel".toByteArray(), "baum.json")
        for (stelle in listOf(14, original.lastIndex)) {
            val manipuliert = original.copyOf().also { it[stelle] = (it[stelle].toInt() xor 1).toByte() }
            erwarteFehler { DatenDateiKrypto(::keyA).entschluesseln(manipuliert, "baum.json") }
        }
        erwarteFehler { DatenDateiKrypto(::keyB).entschluesseln(original, "baum.json") }
    }

    @Test fun `klartextmigration und pair commit bleiben an jeder crashgrenze verlustfrei`() {
        PaarCommitSchritt.entries.forEach { grenze ->
            val ordner = Files.createTempDirectory("at-rest-pair-").toFile()
            try {
                val notizen = ordner.resolve("notizen.json").apply { writeText("N0-attachment") }
                val baum = ordner.resolve("baum.json").apply { writeText("B0-private-key") }
                val crypto = DatenDateiKrypto(::keyA)
                val kodieren = { name: String, bytes: ByteArray -> crypto.verschluesseln(bytes, name) }
                try {
                    WiederherstellungsPaarCommit(ordner, kodieren,
                        { if (it == grenze) throw Prozessabbruch() })
                        .commit("N0-attachment", "B0-private-key", "migration")
                } catch (_: Prozessabbruch) {
                }
                WiederherstellungsPaarCommit(ordner, kodieren = kodieren).wiederaufnehmen()
                val n = notizen.readBytes()
                val b = baum.readBytes()
                val nochKlar = !crypto.istVerschluesselt(n) && !crypto.istVerschluesselt(b)
                val beideGeheim = crypto.istVerschluesselt(n) && crypto.istVerschluesselt(b)
                assertTrue("Gemischtes Paar nach $grenze", nochKlar || beideGeheim)
                if (beideGeheim) {
                    assertArrayEquals("N0-attachment".toByteArray(), crypto.entschluesseln(n, notizen.name))
                    assertArrayEquals("B0-private-key".toByteArray(), crypto.entschluesseln(b, baum.name))
                }
            } finally {
                ordner.deleteRecursively()
            }
        }
    }

    private fun erwarteFehler(block: () -> Unit) {
        try {
            block()
            fail("Manipulation wurde akzeptiert")
        } catch (_: AEADBadTagException) {
        } catch (_: IllegalArgumentException) {
        }
    }

    private class Prozessabbruch : Error()

    companion object {
        private val keyA = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        private val keyB = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    }
}
