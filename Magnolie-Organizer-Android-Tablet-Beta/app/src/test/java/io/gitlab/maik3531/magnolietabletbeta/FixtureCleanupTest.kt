package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class FixtureCleanupTest {
    @Test fun primaryAssertionSurvivesStrictCleanupFailure() {
        val primary=IllegalStateException("actual assertion")
        val cleanup=IllegalStateException("unknown fixture entry")
        cleanupPreservingFailure(primary) {throw cleanup}
        assertEquals(listOf(cleanup),primary.suppressed.toList())
    }
    @Test fun cleanupFailureWithoutPrimaryStillFailsAcceptance() {
        val cleanup=IllegalStateException("unknown fixture entry")
        try {cleanupPreservingFailure(null) {throw cleanup};fail("Cleanup was ignored")}
        catch (failure:IllegalStateException) {assertSame(cleanup,failure)}
    }
    @Test fun successfulCleanupRunsExactlyOnceAndSelfSuppressionIsAvoided() {
        var calls=0;cleanupPreservingFailure(null) {calls++};assertEquals(1,calls)
        val primary=IllegalStateException("actual failure")
        cleanupPreservingFailure(primary) {throw primary}
        assertTrue(primary.suppressed.isEmpty())
    }
}
