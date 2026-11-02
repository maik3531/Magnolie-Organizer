package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.*
import org.junit.Test
import javax.crypto.AEADBadTagException
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

class DeviceTransferProtectionTest {
    @Test fun actualAeadReadbackIsBoundToTheNativeEntryDomainAndExistingKey() {
        var key: SecretKey? = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        val protection = DeviceTransferProtection.fromExistingKeyReader { key }
        val clear = "private synthetic file snapshot".toByteArray()
        val original = clear.copyOf()
        val cipher = protection.seal(clear, "owner/manifest/member/0")
        assertArrayEquals(original, clear)
        assertFalse(cipher.contentEquals(clear))
        assertArrayEquals(clear, protection.open(cipher, "owner/manifest/member/0"))
        assertThrows(AEADBadTagException::class.java) { protection.open(cipher, "other-owner/manifest/member/0") }
        val changed = cipher.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }
        assertThrows(AEADBadTagException::class.java) { protection.open(changed, "owner/manifest/member/0") }
        key = SecretKeySpec(ByteArray(32) { (it + 1).toByte() }, "AES")
        assertThrows(AEADBadTagException::class.java) { protection.open(cipher, "owner/manifest/member/0") }
    }

    @Test fun missingKeyNeverCreatesAReplacementOrResetsOriginalCiphertext() {
        var reads = 0
        var key: SecretKey? = null
        val protection = DeviceTransferProtection.fromExistingKeyReader { reads++; key }
        assertThrows(DeviceTransferKeyUnavailable::class.java) { protection.seal(byteArrayOf(1), "owner/entry") }
        assertEquals(1, reads); assertNull(key)
        val fixture = SecretKeySpec(ByteArray(32) { (it + 2).toByte() }, "AES")
        key = fixture
        val cipher = protection.seal(byteArrayOf(1, 2, 3), "owner/entry")
        val unchanged = cipher.copyOf()
        key = null
        assertThrows(DeviceTransferKeyUnavailable::class.java) { protection.open(cipher, "owner/entry") }
        assertNull(key); assertArrayEquals(unchanged, cipher)
        key = fixture // Restore only the deliberately withheld ephemeral fixture key.
        assertArrayEquals(byteArrayOf(1, 2, 3), protection.open(cipher, "owner/entry"))
    }

    @Test fun invalidBoundsAndAmbiguousDomainsFailBeforeAnyKeyLookup() {
        var reads = 0
        val protection = DeviceTransferProtection.fromExistingKeyReader { reads++; null }
        for (domain in listOf("", "owner\u0000entry", "owner\nentry", "owner\\entry", "a".repeat(1025)))
            assertThrows(IllegalArgumentException::class.java) { protection.seal(byteArrayOf(1), domain) }
        assertThrows(IllegalArgumentException::class.java) { protection.seal(byteArrayOf(), "owner/entry") }
        assertThrows(IllegalArgumentException::class.java) { protection.seal(ByteArray(DeviceTransferProtection.MAX_CLEAR_BYTES + 1), "owner/entry") }
        assertThrows(IllegalArgumentException::class.java) { protection.open(ByteArray(28), "owner/entry") }
        assertEquals(0, reads)
    }
}
