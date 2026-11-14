package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.DatenDateiKrypto
import org.junit.Assert.*
import org.junit.Test
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

class KontaktOriginalSchutzTest {
    private var key: SecretKey? = null
    private var reads = 0
    private var rotations = 0
    private var revocations = 0
    private fun protection() = KontaktOriginalSchutz.fuerTest(
        { reads++; key },
        { rotations++; key = SecretKeySpec(ByteArray(32) { rotations.toByte() }, "AES") },
        { revocations++; key = null })

    @Test fun constructionAndUnavailableKeyNeverCreateAConsentKeyOrPlaintextFallback() {
        val protection = protection()
        assertEquals(0, reads); assertEquals(0, rotations); assertEquals(0, revocations)
        assertThrows(IllegalStateException::class.java) { protection.verschliessen("synthetic".toByteArray()) }
        assertNull(key); assertEquals(0, rotations)
    }

    @Test fun explicitNativeRotationProducesNonPortableAuthenticatedStateAndReadsDoNotRotate() {
        val protection = protection(); protection.neuerEntscheidungsschluessel()
        val clear = "Synthetic peer/source state".toByteArray()
        val first = protection.verschliessen(clear); val second = protection.verschliessen(clear)
        assertFalse(first.contentEquals(second)); assertArrayEquals(clear, protection.oeffnen(first))
        assertArrayEquals(clear, protection.oeffnen(second)); assertEquals(1, rotations)
        assertEquals("Synthetic peer/source state", clear.toString(Charsets.UTF_8))
        assertFalse(first.toString(Charsets.ISO_8859_1).contains("Synthetic peer/source state"))
    }

    @Test fun revokeAndNewDecisionCannotAcceptAnOldEncryptedApprovalRecord() {
        val protection = protection(); protection.neuerEntscheidungsschluessel()
        val old = protection.verschliessen("old source".toByteArray())
        protection.schluesselWiderrufen()
        assertEquals(1, revocations)
        assertThrows(IllegalStateException::class.java) { protection.oeffnen(old) }
        assertEquals(1, rotations)
        protection.neuerEntscheidungsschluessel()
        assertThrows(Exception::class.java) { protection.oeffnen(old) }
        val current = protection.verschliessen("new source".toByteArray())
        assertEquals("new source", protection.oeffnen(current).toString(Charsets.UTF_8))
    }

    @Test fun temporaryKeyAccessLossPreservesTheRecordWithoutRepairingOrRotating() {
        val protection = protection(); protection.neuerEntscheidungsschluessel()
        val state = protection.verschliessen("still desired".toByteArray()); val existing = key
        key = null
        assertThrows(IllegalStateException::class.java) { protection.oeffnen(state) }
        assertEquals(1, rotations); assertEquals(0, revocations)
        key = existing
        assertEquals("still desired", protection.oeffnen(state).toString(Charsets.UTF_8))
    }

    @Test fun otherBookDomainsMalformedCiphertextAndTamperedStateAreRejected() {
        val protection = protection(); protection.neuerEntscheidungsschluessel()
        val state = protection.verschliessen("synthetic source".toByteArray())
        for (blob in listOf(byteArrayOf(), state.copyOf(12), state.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }))
            assertThrows(Exception::class.java) { protection.oeffnen(blob) }
        val other = DatenDateiKrypto({ requireNotNull(key) }).verschluesseln("portable setting".toByteArray(), "baum.json")
        assertThrows(IllegalArgumentException::class.java) { protection.oeffnen(other) }
        assertEquals(1, rotations)
    }

    @Test fun invalidPlaintextBudgetsAreRejectedBeforeKeyAccessOrAnyRotation() {
        val protection = protection()
        for (clear in listOf(byteArrayOf(), ByteArray(256 * 1024 + 1))) {
            assertThrows(IllegalArgumentException::class.java) { protection.klartextPruefen(clear) }
            assertThrows(IllegalArgumentException::class.java) { protection.verschliessen(clear) }
        }
        assertEquals(0, reads); assertEquals(0, rotations); assertEquals(0, revocations)
    }
}
