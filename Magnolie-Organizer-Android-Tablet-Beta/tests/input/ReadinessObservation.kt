package io.gitlab.maik3531.magnolietabletbeta

/** Test-only deadline gate: observation time is independent of waiter scheduling. */
internal class ReadinessObservation(val startedAt: Long, timeoutMs: Long) {
    val deadline = Math.addExact(startedAt, timeoutMs)
    @Volatile var readyObservedAt: Long? = null
        private set
    @Volatile var lastObservedAt: Long? = null
        private set
    @Volatile var finished = false
        private set
    val accepted get() = readyObservedAt?.let { it <= deadline } ?: false

    init { require(startedAt >= 0 && timeoutMs > 0) }
    @Synchronized fun observe(now: Long, ready: Boolean): Boolean {
        require(now >= startedAt && (lastObservedAt == null || now >= lastObservedAt!!))
        if (finished) return true
        lastObservedAt = now
        if (ready && now <= deadline) readyObservedAt = now
        if (readyObservedAt != null || now >= deadline) finished = true
        return finished
    }
    @Synchronized fun stop() { finished = true }
}
