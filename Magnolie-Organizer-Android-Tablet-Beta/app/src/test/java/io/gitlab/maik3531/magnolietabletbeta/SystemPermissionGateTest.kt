package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class SystemPermissionGateTest {
    private val events=SystemSourcePolicy.Kind.EVENTS
    @Test fun activityRecreationQuarantinesOnlyCodeAndCannotAnswerAnOldDocument() {
        val original=SystemPermissionGate.restore(currentProcess="live-process")
        val code=original.begin(events)
        val restored=SystemPermissionGate.restore(original.nextCode,code,"events","live-process","live-process")
        assertEquals(code,restored.pending!!.code)
        try {restored.begin(events);fail("Overlapping OS dialog allowed")} catch(_:IllegalStateException){}
        assertFalse(restored.finish(code+1));assertNotNull(restored.pending)
        assertTrue(restored.finish(code));assertNull(restored.pending)
        val newCode=restored.begin(events)
        assertTrue(newCode>code);assertFalse(restored.finish(code));assertEquals(newCode,restored.pending!!.code)
        // The gate stores neither requestId nor document authority; matching old
        // callback merely frees quarantine and cannot supply a request/reply.
    }
    @Test fun processDeathDiscardsObsoleteQuarantineAndOldResultsCannotCompleteRetry() {
        val old=SystemPermissionGate.restore(currentProcess="old-process");val oldCode=old.begin(events)
        val restarted=SystemPermissionGate.restore(old.nextCode,oldCode,"events","old-process","new-process")
        assertNull(restarted.pending)
        val retry=restarted.begin(events)
        assertTrue(retry>oldCode);assertFalse(restarted.finish(oldCode));assertEquals(retry,restarted.pending!!.code)
    }
    @Test fun restoredQuarantineCanClearByCurrentGrantedPermissionButNotDenial() {
        val gate=SystemPermissionGate.restore(1001,1000,"events","same","same")
        gate.clearIfAlreadyGranted {false};assertNotNull(gate.pending)
        gate.clearIfAlreadyGranted {it==events};assertNull(gate.pending)
        assertEquals(1001,gate.begin(events))
    }
    @Test fun malformedRestoreCannotCreateAnAuthorizingOrUnboundedSlot() {
        for ((code,kind) in listOf(999 to "events",1001 to "events",1000 to "reminders")) {
            val gate=SystemPermissionGate.restore(1001,code,kind,"same","same")
            assertNull(gate.pending);assertEquals(1001,gate.begin(events))
        }
    }
}
