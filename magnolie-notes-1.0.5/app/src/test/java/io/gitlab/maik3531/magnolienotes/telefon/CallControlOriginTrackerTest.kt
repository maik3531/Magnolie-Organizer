package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.assertEquals
import org.junit.Test

class CallControlOriginTrackerTest {
    private val callRef = "123e4567-e89b-42d3-a456-426614174000"
    private val commandRef = "123e4567-e89b-42d3-a456-426614174001"

    @Test fun `eingereichte Annahme und offhook desselben Calls kommt vom Desktop`() {
        val tracker = CallControlOriginTracker()
        tracker.begin(callRef, "unknown")
        tracker.answerSubmitted(callRef, commandRef, 1_000)
        assertEquals("desktop", tracker.offhook(callRef, 2_000))
    }

    @Test fun `offhook ohne Annahme kommt vom Telefon`() {
        val tracker = CallControlOriginTracker()
        tracker.begin(callRef, "unknown")
        assertEquals("phone", tracker.offhook(callRef, 1_000))
    }

    @Test fun `abgelaufene Annahme faellt geschlossen auf Telefon zurueck`() {
        val tracker = CallControlOriginTracker()
        tracker.begin(callRef, "unknown")
        tracker.answerSubmitted(callRef, commandRef, 1_000)
        assertEquals("phone", tracker.offhook(callRef, 11_001))
    }

    @Test fun `fehlgeschlagene Annahme markiert den Call nicht als Desktop`() {
        val tracker = CallControlOriginTracker()
        tracker.begin(callRef, "unknown")
        tracker.answerSubmitted(callRef, commandRef, 1_000)
        tracker.answerFailed(callRef, commandRef)
        assertEquals("phone", tracker.offhook(callRef, 2_000))
    }

    @Test fun `Ablehnung eines anderen Befehls loescht den exakten Marker nicht`() {
        val tracker = CallControlOriginTracker()
        tracker.begin(callRef, "unknown")
        tracker.answerSubmitted(callRef, commandRef, 1_000)
        tracker.answerFailed(callRef, "123e4567-e89b-42d3-a456-426614174009")
        assertEquals("desktop", tracker.offhook(callRef, 2_000))
    }

    @Test fun `idle behaelt Herkunft im Ereignis und loescht sie danach`() {
        val tracker = CallControlOriginTracker()
        tracker.begin(callRef, "unknown")
        tracker.answerSubmitted(callRef, commandRef, 1_000)
        tracker.offhook(callRef, 2_000)
        assertEquals("desktop", tracker.origin(callRef, 3_000))
        tracker.clear(callRef)
        assertEquals("unknown", tracker.origin(callRef, 3_000))
    }

    @Test fun `direkter Ausgang ist Desktop und manuelles offhook Telefon`() {
        val tracker = CallControlOriginTracker()
        tracker.begin(callRef, "desktop")
        assertEquals("desktop", tracker.offhook(callRef, 1_000))
        tracker.begin("123e4567-e89b-42d3-a456-426614174002", "phone")
        assertEquals("phone", tracker.origin("123e4567-e89b-42d3-a456-426614174002", 2_000))
    }
}
