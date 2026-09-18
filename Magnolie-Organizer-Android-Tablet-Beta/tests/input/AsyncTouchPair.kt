package io.gitlab.maik3531.magnolietabletbeta

/** Test-driver scheduling only; shared with the fake-clock JVM regression. */
internal object AsyncTouchPair {
    data class Event(val down: Boolean, val downTime: Long, val eventTime: Long)
    data class Delivery(val event: Event, val callAt: Long, val returnedAt: Long, val accepted: Boolean)

    fun inject(now: () -> Long, sleep: (Long) -> Unit,
               send: (Event, Boolean) -> Boolean): List<Delivery> {
        val result = mutableListOf<Delivery>()
        val downTime = now()
        fun emit(down: Boolean) {
            val event = Event(down, downTime, now())
            val called = now()
            val accepted = send(event, false) // Never wait for UI input completion.
            result.add(Delivery(event, called, now(), accepted))
            check(accepted) { "Native injection rejected ${if (down) "DOWN" else "UP"}" }
        }
        emit(true)
        val remaining = downTime + 40 - now()
        if (remaining > 0) sleep(remaining)
        emit(false) // Actual monotonic uptime, never backdate a delayed UP.
        return result
    }
}
