package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test

class NativeOsOffsetComparisonTest {
    @Test fun publicMillisecondOffsetsAreComparedToOracleSecondsExactly() {
        for(seconds in listOf(-86400L, -18000L, -1L, 0L, 1L, 3600L, 39600L, 86400L))
            assertTrue(NativeOsOffsetComparison(seconds, (seconds * 1000).toInt()).matches)
        assertFalse(NativeOsOffsetComparison(3600, 3600).matches) // Original mixed-unit failure.
        assertFalse(NativeOsOffsetComparison(3600, 3600001).matches) // No truncation hiding discrepancies.
        assertFalse(NativeOsOffsetComparison(-1, -999).matches)
        assertFalse(NativeOsOffsetComparison(3600, 7200000).matches) // Genuine rule mismatch remains visible.
    }
    @Test fun impossibleOffsetsAreRejectedBeforeMultiplication() {
        for(seconds in listOf(Long.MIN_VALUE, -86401L, 86401L, Long.MAX_VALUE)) {
            try { NativeOsOffsetComparison(seconds, 0); fail("Accepted unbounded offset") }
            catch (_: IllegalArgumentException) { }
        }
    }
}
