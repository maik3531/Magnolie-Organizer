package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class SystemImportPolicyTest {
    private val contacts = SystemSourcePolicy.Kind.CONTACTS
    private val events = SystemSourcePolicy.Kind.EVENTS
    private fun source(kind: SystemSourcePolicy.Kind = contacts) = SystemSourcePolicy.uid(kind, "native-test-source", "account")
    private fun message(kind: SystemSourcePolicy.Kind = contacts) = JSONObject().put("cmd", "android_systemimport")
        .put("art", kind.wire).put("sourceUid", source(kind)).put("requestId", "read-1")
        .put("session", "page-1").put("revision", "book-1").also {
            if (kind == events) it.put("from", 0L).put("to", SystemImportRequest.MAX_WINDOW)
                .put("dateFrom", "1970-01-01").put("dateTo", "1971-01-01")
        }
    private fun rejected(block: () -> Unit) {
        try { block(); fail("Unsafe provider candidate was accepted") }
        catch (_: IllegalArgumentException) {} catch (_: IllegalStateException) {}
    }
    private fun detail(mime: String, vararg fields: String?) = SystemImportPolicy.Detail(mime, fields.toList())
    private fun millis(value: String) = Instant.parse(value).toEpochMilli()
    private fun instance(begin: String = "2030-04-01T10:00:37Z", end: String = "2030-04-01T11:00:37Z", allDay: Boolean = false) =
        SystemImportPolicy.CalendarInstance("17", millis(begin), millis(end), allDay, "Appointment", "Private note", "Place")

    @Test fun explicitTypedSourceReadHasNoImplicitWindowOrWriteFlags() {
        val parsed = SystemImportRequest.parse(message())
        assertEquals(contacts, parsed.kind); assertNull(parsed.from); assertNull(parsed.to)
        assertEquals("page-1", parsed.session); assertEquals("book-1", parsed.revision)
        assertEquals(SystemImportRequest.MAX_WINDOW, SystemImportRequest.parse(message(events)).to)
        for (value in listOf(message().put("write", true), message().put("records", "untrusted"),
            message().put("from", 0), message().put("art", "tasks"), message().put("sourceUid", source(events)),
            message().put("sourceUid", "content://contacts/1"), message().put("requestId", false),
            message().put("session", ""), message().also { it.remove("revision") })) rejected { SystemImportRequest.parse(value) }
    }

    @Test fun timeWindowRejectsOverflowCoercionAndUnboundedReads() {
        for (value in listOf(message(events).put("to", SystemImportRequest.MAX_WINDOW + 2 * SystemImportWindow.DAY + 1),
            message(events).put("to", 0), message(events).put("from", 1).put("to", 0),
            message(events).put("from", "0"), message(events).put("to", 1.5),
            message(events).put("from", Long.MIN_VALUE), message(events).put("to", Long.MAX_VALUE),
            message(events).also { it.remove("to") })) rejected { SystemImportRequest.parse(value) }
        assertEquals(-86400000L, SystemImportRequest.parse(message(events).put("from", -86400000L).put("to", 0L)
            .put("dateFrom", "1969-12-31").put("dateTo", "1969-12-31")).from)
    }

    @Test fun selectedDatesAreStrictBoundedAndCannotInflateTheNativeUnionQuery() {
        for (value in listOf(message(events).put("dateFrom", "1970-1-1"), message(events).put("dateFrom", "1970-02-30"),
            message(events).put("dateFrom", "0000-01-01"), message(events).put("dateTo", "1969-12-31"),
            message(events).put("dateTo", "1971-01-02"), message(events).put("dateFrom", 0),
            message(events).also { it.remove("dateTo") },
            message(events).put("dateFrom", "2030-01-01").put("dateTo", "2030-01-02")))
            rejected { SystemImportRequest.parse(value) }
        // A valid 366-calendar-day selection may last 366 days plus one hour across an offset change.
        assertEquals(SystemImportRequest.MAX_WINDOW + 3_600_000L,
            SystemImportRequest.parse(message(events).put("to", SystemImportRequest.MAX_WINDOW + 3_600_000L)).to)
    }

    @Test fun berlinDayDoesNotImportThePreviousUtcAllDayButKeepsLocalTimedEvents() {
        val window = SystemImportWindow.of(SystemImportRequest.parse(message(events)
            .put("from", millis("2026-11-25T23:00:00Z")).put("to", millis("2026-11-26T23:00:00Z"))
            .put("dateFrom", "2026-11-26").put("dateTo", "2026-11-26")))
        assertEquals(millis("2026-11-25T23:00:00Z"), window.queryFrom)
        assertEquals(millis("2026-11-27T00:00:00Z"), window.queryTo)
        assertFalse(window.contains(millis("2026-11-25T00:00:00Z"), millis("2026-11-26T00:00:00Z"), true))
        assertTrue(window.contains(millis("2026-11-26T00:00:00Z"), millis("2026-11-27T00:00:00Z"), true))
        assertFalse(window.contains(millis("2026-11-27T00:00:00Z"), millis("2026-11-28T00:00:00Z"), true))
        assertTrue(window.contains(millis("2026-11-25T23:30:00Z"), millis("2026-11-26T00:30:00Z"), false))
        assertFalse(window.contains(millis("2026-11-26T23:00:00Z"), millis("2026-11-27T00:00:00Z"), false))
    }

    @Test fun westernZoneQueriesTheFullUtcDayWithoutImportingTheFollowingAllDay() {
        val window = SystemImportWindow.of(SystemImportRequest.parse(message(events)
            .put("from", millis("2026-11-26T08:00:00Z")).put("to", millis("2026-11-27T08:00:00Z"))
            .put("dateFrom", "2026-11-26").put("dateTo", "2026-11-26")))
        assertEquals(millis("2026-11-26T00:00:00Z"), window.queryFrom)
        assertEquals(millis("2026-11-27T08:00:00Z"), window.queryTo)
        assertTrue(window.contains(millis("2026-11-26T00:00:00Z"), millis("2026-11-27T00:00:00Z"), true))
        assertFalse(window.contains(millis("2026-11-27T00:00:00Z"), millis("2026-11-28T00:00:00Z"), true))
        assertFalse(window.contains(millis("2026-11-26T07:00:00Z"), millis("2026-11-26T08:00:00Z"), false))
        assertTrue(window.contains(millis("2026-11-27T07:30:00Z"), millis("2026-11-27T08:30:00Z"), false))
    }

    @Test fun multiDayDateSpansUseExclusiveEndsAndTimedZeroDurationKeepsItsOwnBoundary() {
        val window = SystemImportWindow.of(SystemImportRequest.parse(message(events)
            .put("from", millis("2026-11-25T23:00:00Z")).put("to", millis("2026-11-28T23:00:00Z"))
            .put("dateFrom", "2026-11-26").put("dateTo", "2026-11-28")))
        assertTrue(window.contains(millis("2026-11-24T00:00:00Z"), millis("2026-11-27T00:00:00Z"), true))
        assertTrue(window.contains(millis("2026-11-28T00:00:00Z"), millis("2026-12-02T00:00:00Z"), true))
        assertFalse(window.contains(millis("2026-11-24T00:00:00Z"), millis("2026-11-26T00:00:00Z"), true))
        assertFalse(window.contains(millis("2026-11-29T00:00:00Z"), millis("2026-12-02T00:00:00Z"), true))
        assertTrue(window.contains(window.from, window.from, false)); assertFalse(window.contains(window.to, window.to, false))
        rejected { window.contains(millis("2026-11-26T01:00:00Z"), millis("2026-11-27T01:00:00Z"), true) }
    }

    @Test fun failureCannotBeMisreadAsAnEmptySuccessfulProviderSnapshot() {
        val result = SystemImportRequest.parse(message()).failure("permission_required")
        assertFalse(result.getBoolean("ok")); assertFalse(result.has("records")); assertFalse(result.has("complete"))
        assertEquals("permission_required", result.getString("errorCode")); assertEquals("read-1", result.getString("requestId"))
        assertEquals("book-1", result.getString("revision"))
        val eventsFailure = SystemImportRequest.parse(message(events)).failure("provider_changed")
        assertEquals("1970-01-01", eventsFailure.getString("dateFrom"))
        assertEquals("1971-01-01", eventsFailure.getString("dateTo"))
        assertEquals(SystemImportRequest.MAX_WINDOW, eventsFailure.getLong("to"))
    }

    @Test fun nativeIdentitiesAreSourceBoundAndDoNotDiscloseRawAccountNames() {
        val id = SystemImportPolicy.recordId(contacts, source(), "7")
        assertTrue(id.matches(Regex("android-contact:[0-9a-f]{64}")))
        assertEquals(id, SystemImportPolicy.recordId(contacts, source(), "7"))
        assertNotEquals(id, SystemImportPolicy.recordId(contacts, source(), "8"))
        assertNotEquals(id, SystemImportPolicy.recordId(contacts, SystemSourcePolicy.uid(contacts, "other"), "7"))
        assertNotEquals(SystemImportPolicy.recordId(events, source(events), "7", "10"),
            SystemImportPolicy.recordId(events, source(events), "7", "11"))
    }

    @Test fun contactValuesKeepNativeLabelsMultipleNumbersAndStructuredAddresses() {
        val data = SystemImportPolicy.contact(source(), "7", "Fallback", listOf(
            detail(SystemImportPolicy.NAME, "Dr. Ada Lovelace", "Ada", "Lovelace", "Dr."),
            detail(SystemImportPolicy.PHONE, "+49 30 12345", "1", null),
            detail(SystemImportPolicy.PHONE, "+49 171 23456", "17", null),
            detail(SystemImportPolicy.PHONE, "030 45678", "0", "Werkstatt"),
            detail(SystemImportPolicy.EMAIL, "ada@example.test", "2", null),
            detail(SystemImportPolicy.POSTAL, "Formatted", "1", null, "Teststraße 1", "Postfach 2", "Hof", "Berlin", "BE", "10115", "Deutschland"),
            detail(SystemImportPolicy.NOTE, "Line one\nLine two"), detail(SystemImportPolicy.ORGANIZATION, "Analytical Engines")))
        assertEquals("Ada", data.getString("vorname")); assertEquals("Lovelace", data.getString("nachname"))
        assertEquals("Dr. Ada Lovelace", data.getString("anzeigename")); assertFalse(data.getBoolean("sync"))
        val phones = data.getJSONArray("telefone")
        assertEquals(3, phones.length()); assertEquals("HOME", phones.getJSONObject(0).getJSONArray("typen").getString(0))
        assertEquals(listOf("WORK", "CELL"), (0..1).map { phones.getJSONObject(1).getJSONArray("typen").getString(it) })
        assertEquals("Werkstatt", phones.getJSONObject(2).getString("label")); assertEquals("030 45678", phones.getJSONObject(2).getString("wert"))
        assertEquals("WORK", data.getJSONArray("emailEintraege").getJSONObject(0).getJSONArray("typen").getString(0))
        val address = data.getJSONArray("anschriften").getJSONObject(0)
        assertEquals("Teststraße 1", address.getString("strasse")); assertEquals("Postfach 2", address.getString("postfach"))
        assertEquals("10115", address.getString("plz")); assertEquals("Hof", address.getString("zusatz"))
        assertEquals("Line one\nLine two", data.getString("notiz"))
    }

    @Test fun birthdaysKeepUnknownYearsAndUnsupportedDatesWithoutInventingValues() {
        val data = SystemImportPolicy.contact(source(), "2", "Person", listOf(
            detail(SystemImportPolicy.EVENT, "--02-29", "3"), detail(SystemImportPolicy.EVENT, "20200430", "1"),
            detail(SystemImportPolicy.EVENT, "2023-02-29", "3"), detail(SystemImportPolicy.EVENT, "0000-01-01", "1"),
            detail(SystemImportPolicy.EVENT, "2030-01-01", "0", "Graduation")))
        assertEquals("--02-29", data.getString("geburtstag")); assertEquals("2020-04-30", data.getString("jubilaeum"))
        assertEquals(3, data.getJSONArray("androidContactDates").length())
        assertEquals("2023-02-29", data.getJSONArray("androidContactDates").getJSONObject(0).getString("value"))
        assertEquals("Graduation", data.getJSONArray("androidContactDates").getJSONObject(2).getString("label"))
    }

    @Test fun oversizedOrUnknownContactRowsFailWithoutTruncatingTheirContent() {
        rejected { SystemImportPolicy.contact(source(), "1", "Person", listOf(detail(SystemImportPolicy.NOTE, "x".repeat(65537)))) }
        rejected { SystemImportPolicy.contact(source(), "1", "Person", listOf(detail("unknown/provider", "value"))) }
        rejected { SystemImportPolicy.contact(source(), "content://untrusted", "Person", emptyList()) }
        val displayOnly = SystemImportPolicy.contact(source(), "1", "Organization", emptyList())
        assertEquals("Organization", displayOnly.getString("anzeigename")); assertEquals("", displayOnly.getString("vorname"))
        assertEquals("Organization", displayOnly.getString("nachname"))
    }

    @Test fun timedInstancesRetainUtcSecondsWithoutImportingRecurrenceOrReminderConsent() {
        val data = SystemImportPolicy.calendar(source(events), instance())
        assertEquals("2030-04-01", data.getString("datum")); assertEquals("10:00:37", data.getString("zeit"))
        assertEquals("", data.getString("endDatum")); assertEquals("11:00:37", data.getString("endZeit"))
        assertEquals("UTC", data.getString("icsAnzeigeZeitzone")); assertFalse(data.getBoolean("standardErinnerung"))
        assertFalse(data.getBoolean("sync")); assertEquals("none", data.getJSONObject("wiederholung").getString("art"))
        assertEquals("DTSTART:20300401T100037Z", data.getJSONArray("icsRoundtrip").getString(0))
        assertEquals("DTEND:20300401T110037Z", data.getJSONArray("icsRoundtrip").getString(1))
    }

    @Test fun allDayExclusiveEndBecomesInclusiveCanonicalLastDay() {
        val multi = SystemImportPolicy.calendar(source(events), instance("2030-04-01T00:00:00Z", "2030-04-04T00:00:00Z", true))
        assertEquals("2030-04-03", multi.getString("endDatum")); assertEquals("", multi.getString("zeit"))
        assertEquals("DTEND;VALUE=DATE:20300404", multi.getJSONArray("icsRoundtrip").getString(1))
        val single = SystemImportPolicy.calendar(source(events), instance("2030-04-01T00:00:00Z", "2030-04-02T00:00:00Z", true))
        assertEquals("", single.getString("endDatum"))
        rejected { SystemImportPolicy.calendar(source(events), instance("2030-04-01T01:00:00Z", "2030-04-02T01:00:00Z", true)) }
    }

    @Test fun invalidDurationAndSubsecondLossFailAndZeroDurationIsPreserved() {
        rejected { SystemImportPolicy.calendar(source(events), instance("2030-04-01T10:00:00Z", "2030-04-01T09:00:00Z")) }
        rejected { SystemImportPolicy.calendar(source(events), instance("2030-04-01T10:00:00.500Z", "2030-04-01T11:00:00Z")) }
        rejected { SystemImportPolicy.calendar(source(events), instance("2030-04-01T00:00:00Z", "2030-04-01T00:00:00Z", true)) }
        val zero = SystemImportPolicy.calendar(source(events), instance("2030-04-01T10:00:00Z", "2030-04-01T10:00:00Z"))
        assertTrue(zero.getBoolean("icsNullDauer")); assertEquals("10:00", zero.getString("endZeit"))
    }

    @Test fun duplicateIdentityAndMismatchedDataRejectTheWholeCandidate() {
        val batch = SystemImportPolicy.Batch(SystemImportRequest.parse(message()))
        val data = SystemImportPolicy.contact(source(), "1", "Person", emptyList())
        val id = data.getString("uid")
        batch.add(id, data)
        rejected { batch.add(id, data) }
        rejected { SystemImportPolicy.Batch(SystemImportRequest.parse(message())).add("other", data) }
    }

    @Test fun recordAndByteLimitsDoNotReturnAClaimedCompleteTruncatedSnapshot() {
        val request = SystemImportRequest.parse(message())
        val records = SystemImportPolicy.Batch(request)
        for (i in 0 until SystemImportPolicy.MAX_RECORDS) records.add("id-$i", JSONObject().put("uid", "id-$i"))
        rejected { records.add("one-too-many", JSONObject().put("uid", "one-too-many")) }
        val bytes = SystemImportPolicy.Batch(request)
        rejected { bytes.add("large", JSONObject().put("uid", "large").put("notiz", "x".repeat(SystemImportPolicy.MAX_BYTES))) }
    }

    @Test fun successfulEmptyImportIsExplicitlyScopedAndDoesNotClaimAllCalendarData() {
        val request = SystemImportRequest.parse(message(events))
        val result = SystemImportPolicy.Batch(request).result()
        assertTrue(result.getBoolean("ok")); assertTrue(result.getBoolean("complete"))
        assertEquals("calendar-instances-window", result.getString("scope")); assertEquals(0, result.getJSONArray("records").length())
        assertEquals(0L, result.getLong("from")); assertEquals(SystemImportRequest.MAX_WINDOW, result.getLong("to"))
        assertEquals("1970-01-01", result.getString("dateFrom")); assertEquals("1971-01-01", result.getString("dateTo"))
        assertFalse(result.has("delete")); assertFalse(result.has("write")); assertFalse(result.has("sync"))
    }
}
