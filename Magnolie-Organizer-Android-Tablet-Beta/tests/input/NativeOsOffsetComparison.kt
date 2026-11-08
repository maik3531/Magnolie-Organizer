package io.gitlab.maik3531.magnolietabletbeta

/** Test-only unit boundary: public TimeZone offsets are milliseconds, provider/oracle offsets seconds. */
data class NativeOsOffsetComparison(val expectedOffsetSeconds: Long, val actualOffsetMilliseconds: Int) {
    init { require(expectedOffsetSeconds in -86400L..86400L) }
    // Compare without lossy division: even a subsecond discrepancy remains visible.
    val matches: Boolean get() = expectedOffsetSeconds * 1000L == actualOffsetMilliseconds.toLong()
}
