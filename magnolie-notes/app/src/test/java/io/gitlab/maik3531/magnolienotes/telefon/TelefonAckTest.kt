package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.assertThrows
import org.junit.Test

class TelefonAckTest {
    @Test fun temporaryFailureIsAValidRejectionButNeverAnAcceptance() {
        val id = "33333333-3333-4333-8333-333333333333"
        TelefonNachrichten.validateAck(TelefonNachrichten.ack(id, "rejected", "temporary_failure"))
        for (status in listOf("accepted", "duplicate")) {
            assertThrows(TelefonProtokollFehler::class.java) {
                TelefonNachrichten.validateAck(TelefonNachrichten.ack(id, status, "temporary_failure"))
            }
        }
        assertThrows(TelefonProtokollFehler::class.java) {
            TelefonNachrichten.validateAck(TelefonNachrichten.ack(id, "rejected", "unknown_failure"))
        }
    }
}
