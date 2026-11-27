package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant

/** Contract examples against the unchanged PR mapper; synthetic inputs, no Android provider runtime. */
class ProviderIdentityBeforeTest {
    @Test fun resyncedContactWithSameSourceIdentityMustNotBecomeNew() {
        val source = SystemSourcePolicy.uid(SystemSourcePolicy.Kind.CONTACTS, "contacts", "test.example", "account", null)
        // Android documents SOURCE_ID preservation after storage-clear/resync. This same
        // fixture source identity is absent from the current native projection/signature.
        val first = SystemImportPolicy.contact(source, "7", "Test Person", emptyList())
        val resynced = SystemImportPolicy.contact(source, "42", "Test Person", emptyList())
        assertEquals("Same SOURCE_ID=contact-one after row recreation", first.getString("uid"), resynced.getString("uid"))
    }

    @Test fun movingOneTimeEventMustNotBecomeNewEventIdentity() {
        val source = SystemSourcePolicy.uid(SystemSourcePolicy.Kind.EVENTS, "calendar", "test.example", "account", "3")
        val begin = Instant.parse("2030-04-01T10:00:00Z").toEpochMilli()
        val first = SystemImportPolicy.CalendarInstance("17", begin, begin + 3600000, false, "Test event", "", "")
        val moved = first.copy(begin = begin + 7200000, end = begin + 10800000)
        assertEquals("Same one-time Events._ID after DTSTART update", SystemImportPolicy.calendar(source, first).getString("uid"),
            SystemImportPolicy.calendar(source, moved).getString("uid"))
    }
}
