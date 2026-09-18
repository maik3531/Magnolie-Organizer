package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class AsyncTouchPairTest {
    @Test fun queuesBothEventsWithoutWaitingForAnyUiReceipt() {
        var clock = 1000L
        val queued = mutableListOf<AsyncTouchPair.Event>()
        val flags = mutableListOf<Boolean>()
        // The fake UI never consumes its queue while injection is running.
        val result = AsyncTouchPair.inject({ clock }, { clock += it }) { event, sync ->
            flags.add(sync); queued.add(event); clock += 7; true
        }
        assertEquals(listOf(false, false), flags)
        assertEquals(listOf(true, false), queued.map { it.down })
        assertEquals(listOf(1000L, 1000L), queued.map { it.downTime })
        assertEquals(listOf(1000L, 1040L), queued.map { it.eventTime })
        assertEquals(listOf(7L, 7L), result.map { it.returnedAt - it.callAt })
    }

    @Test fun delayedInjectionReturnDoesNotForgeEarlierUpTimestamp() {
        var clock = 2000L
        val result = AsyncTouchPair.inject({ clock }, { fail("No extra hold after delayed DOWN") }) { _, sync ->
            assertFalse(sync); clock += 90; true
        }
        assertEquals(2000L, result[1].event.downTime)
        assertEquals(2090L, result[1].event.eventTime)
        assertTrue(result[1].event.eventTime > result[0].event.eventTime)
    }

    @Test fun rejectedInjectionCannotBeReportedAsSuccess() {
        var calls = 0
        try {
            AsyncTouchPair.inject({ 1000L }, {}) { _, sync -> assertFalse(sync); calls++; false }
            fail("Rejected DOWN must fail the driver")
        } catch (expected: IllegalStateException) {
            assertEquals(1, calls)
        }
    }
}
