package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class ReadinessObservationTest {
    @Test fun earlyObservationSurvivesDelayedWaiterScheduling() {
        val gate = ReadinessObservation(100, 25000)
        assertFalse(gate.observe(200, false))
        assertTrue(gate.observe(24900, true))
        assertTrue(gate.observe(40000, true))
        assertTrue(gate.accepted)
        assertEquals(24900L, gate.readyObservedAt)
    }
    @Test fun lateReadinessDoesNotBecomeSuccess() {
        val gate = ReadinessObservation(100, 25000)
        assertFalse(gate.observe(25000, false))
        assertTrue(gate.observe(25101, true))
        assertFalse(gate.accepted)
        assertNull(gate.readyObservedAt)
    }
    @Test fun deadlineObservationIsInclusiveAndCannotBeRewritten() {
        val gate = ReadinessObservation(100, 25000)
        assertTrue(gate.observe(25100, true))
        gate.stop()
        assertTrue(gate.observe(30000, false))
        assertTrue(gate.accepted)
        assertEquals(25100L, gate.readyObservedAt)
    }
    @Test fun timeoutAndCancellationCannotAcceptLaterReadiness() {
        val timedOut = ReadinessObservation(100, 25000)
        assertTrue(timedOut.observe(25100, false))
        assertTrue(timedOut.observe(25101, true))
        assertFalse(timedOut.accepted)
        val cancelled = ReadinessObservation(100, 25000)
        cancelled.stop()
        assertTrue(cancelled.observe(200, true))
        assertFalse(cancelled.accepted)
    }
    @Test(expected = IllegalArgumentException::class) fun backwardsObservationIsRejected() {
        val gate = ReadinessObservation(100, 25000)
        gate.observe(200, false)
        gate.observe(199, true)
    }
}
