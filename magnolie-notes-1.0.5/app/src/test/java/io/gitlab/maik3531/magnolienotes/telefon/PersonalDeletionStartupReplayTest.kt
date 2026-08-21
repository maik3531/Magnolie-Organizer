package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.assertEquals
import org.junit.Test

class PersonalDeletionStartupReplayTest {
    @Test fun `expired and tampered runs retain decisions and do not stop replay`() {
        val pending = listOf("expired", "tampered", "current")
        val queued = mutableListOf<String>()

        replayPendingPersonalDeletions(pending, { decision ->
            when (decision) {
                "expired" -> null
                "tampered" -> error("authenticated run metadata mismatch")
                else -> "any"
            }
        }) { decision, policy -> queued += "$decision:$policy" }

        assertEquals(listOf("current:any"), queued)
        assertEquals(listOf("expired", "tampered", "current"), pending)

        val reconciled = mutableListOf<String>()
        replayPendingPersonalDeletions(pending.take(2), { "wifi_only" }) { decision, policy ->
            reconciled += "$decision:$policy"
        }
        assertEquals(listOf("expired:wifi_only", "tampered:wifi_only"), reconciled)
    }
}
