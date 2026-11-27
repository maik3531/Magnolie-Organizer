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
    private val device = "0123456789abcdef"
    private fun raw(id: String = "7", sourceId: String? = null, backupId: String? = null) =
        SystemImportPolicy.RawContact(id, "1", "Test Person", sourceId, backupId)
    private fun identity(id: String = "7") = SystemImportPolicy.contactIdentity(source(), raw(id), device)
    private fun contact(id: String, name: String, details: List<SystemImportPolicy.Detail>) =
        SystemImportPolicy.contact(identity(id), name, details)
    private fun failedWith(code: String, block: () -> Unit) {
        try { block(); fail("Expected failure: $code") }
        catch (error: IllegalArgumentException) { assertEquals(code, error.message) }
        catch (error: IllegalStateException) { assertEquals(code, error.message) }
    }
    private fun millis(value: String) = Instant.parse(value).toEpochMilli()
    private fun instance(begin: String = "2030-04-01T10:00:37Z", end: String = "2030-04-01T11:00:37Z", allDay: Boolean = false) =
        SystemImportPolicy.CalendarInstance("17", millis(begin), millis(end), allDay, "Appointment", "Private note", "Place")
    private fun eventIdentity(value: SystemImportPolicy.CalendarInstance) = SystemImportPolicy.eventIdentity(source(events), value, device)
    private fun calendar(value: SystemImportPolicy.CalendarInstance) = SystemImportPolicy.calendar(eventIdentity(value), value)

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
        val data = contact("7", "Fallback", listOf(
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
        val data = contact("2", "Person", listOf(
            detail(SystemImportPolicy.EVENT, "--02-29", "3"), detail(SystemImportPolicy.EVENT, "20200430", "1"),
            detail(SystemImportPolicy.EVENT, "2023-02-29", "3"), detail(SystemImportPolicy.EVENT, "0000-01-01", "1"),
            detail(SystemImportPolicy.EVENT, "2030-01-01", "0", "Graduation")))
        assertEquals("--02-29", data.getString("geburtstag")); assertEquals("2020-04-30", data.getString("jubilaeum"))
        assertEquals(3, data.getJSONArray("androidContactDates").length())
        assertEquals("2023-02-29", data.getJSONArray("androidContactDates").getJSONObject(0).getString("value"))
        assertEquals("Graduation", data.getJSONArray("androidContactDates").getJSONObject(2).getString("label"))
    }

    @Test fun oversizedOrUnknownContactRowsFailWithoutTruncatingTheirContent() {
        rejected { contact("1", "Person", listOf(detail(SystemImportPolicy.NOTE, "x".repeat(65537)))) }
        rejected { contact("1", "Person", listOf(detail("unknown/provider", "value"))) }
        rejected { contact("content://untrusted", "Person", emptyList()) }
        val displayOnly = contact("1", "Organization", emptyList())
        assertEquals("Organization", displayOnly.getString("anzeigename")); assertEquals("", displayOnly.getString("vorname"))
        assertEquals("Organization", displayOnly.getString("nachname"))
    }

    @Test fun timedInstancesRetainUtcSecondsWithoutImportingRecurrenceOrReminderConsent() {
        val data = calendar(instance())
        assertEquals("2030-04-01", data.getString("datum")); assertEquals("10:00:37", data.getString("zeit"))
        assertEquals("", data.getString("endDatum")); assertEquals("11:00:37", data.getString("endZeit"))
        assertEquals("UTC", data.getString("icsAnzeigeZeitzone")); assertFalse(data.getBoolean("standardErinnerung"))
        assertFalse(data.getBoolean("sync")); assertEquals("none", data.getJSONObject("wiederholung").getString("art"))
        assertEquals("DTSTART:20300401T100037Z", data.getJSONArray("icsRoundtrip").getString(0))
        assertEquals("DTEND:20300401T110037Z", data.getJSONArray("icsRoundtrip").getString(1))
    }

    @Test fun allDayExclusiveEndBecomesInclusiveCanonicalLastDay() {
        val multi = calendar(instance("2030-04-01T00:00:00Z", "2030-04-04T00:00:00Z", true))
        assertEquals("2030-04-03", multi.getString("endDatum")); assertEquals("", multi.getString("zeit"))
        assertEquals("DTEND;VALUE=DATE:20300404", multi.getJSONArray("icsRoundtrip").getString(1))
        val single = calendar(instance("2030-04-01T00:00:00Z", "2030-04-02T00:00:00Z", true))
        assertEquals("", single.getString("endDatum"))
        rejected { calendar(instance("2030-04-01T01:00:00Z", "2030-04-02T01:00:00Z", true)) }
    }

    @Test fun invalidDurationAndSubsecondLossFailAndZeroDurationIsPreserved() {
        rejected { calendar(instance("2030-04-01T10:00:00Z", "2030-04-01T09:00:00Z")) }
        rejected { calendar(instance("2030-04-01T10:00:00.500Z", "2030-04-01T11:00:00Z")) }
        rejected { calendar(instance("2030-04-01T00:00:00Z", "2030-04-01T00:00:00Z", true)) }
        val zero = calendar(instance("2030-04-01T10:00:00Z", "2030-04-01T10:00:00Z"))
        assertTrue(zero.getBoolean("icsNullDauer")); assertEquals("10:00", zero.getString("endZeit"))
    }

    @Test fun duplicateIdentityAndMismatchedDataRejectTheWholeCandidate() {
        val batch = SystemImportPolicy.Batch(SystemImportRequest.parse(message()))
        val data = contact("1", "Person", emptyList())
        val id = data.getString("uid")
        batch.add(id, data, identity("1"))
        rejected { batch.add(id, data, identity("1")) }
        rejected { SystemImportPolicy.Batch(SystemImportRequest.parse(message())).add("other", data, identity("1")) }
        rejected { SystemImportPolicy.Batch(SystemImportRequest.parse(message())).add(id, data) }
    }

    @Test fun recordAndByteLimitsDoNotReturnAClaimedCompleteTruncatedSnapshot() {
        val request = SystemImportRequest.parse(message(events))
        val records = SystemImportPolicy.Batch(request)
        for (i in 0 until SystemImportPolicy.MAX_RECORDS)
            records.add("id-$i", JSONObject().put("uid", "id-$i"), SystemImportPolicy.EventIdentity("id-$i", "single-event"))
        rejected { records.add("one-too-many", JSONObject().put("uid", "one-too-many"), SystemImportPolicy.EventIdentity("one-too-many", "single-event")) }
        val bytes = SystemImportPolicy.Batch(request)
        rejected { bytes.add("large", JSONObject().put("uid", "large").put("notiz", "x".repeat(SystemImportPolicy.MAX_BYTES)),
            SystemImportPolicy.EventIdentity("large", "single-event")) }
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

    @Test fun accountSourceIdentitySurvivesRawRowRecreationAndDeviceChanges() {
        val original = SystemImportPolicy.contactIdentity(source(), raw(sourceId = "contact-one"), device)
        val resynced = SystemImportPolicy.contactIdentity(source(), raw("42", "contact-one"), "fedcba9876543210")
        assertEquals("source-id", original.kind)
        assertEquals(original.recordId, resynced.recordId)
        assertNotEquals(original.rowBinding, resynced.rowBinding)
        assertNotEquals(original.recordId, SystemImportPolicy.contactIdentity(source(), raw(sourceId = "contact-two"), device).recordId)
        assertNotEquals(original.recordId, SystemImportPolicy.contactIdentity(SystemSourcePolicy.uid(contacts, "other-account-or-data-set"),
            raw(sourceId = "contact-one"), device).recordId)
    }

    @Test fun providerBackupIdentityIsUsedOnlyWithoutSourceIdentityAndHasItsOwnNamespace() {
        val backup = SystemImportPolicy.contactIdentity(source(), raw(backupId = "persistent-one"), device)
        assertEquals("backup-id", backup.kind)
        assertEquals(backup.recordId, SystemImportPolicy.contactIdentity(source(), raw("42", backupId = "persistent-one"), device).recordId)
        val sourceId = SystemImportPolicy.contactIdentity(source(), raw(sourceId = "persistent-one", backupId = "persistent-one"), device)
        assertEquals("source-id", sourceId.kind); assertNotEquals(sourceId.recordId, backup.recordId)
    }

    @Test fun fallbackIdentityAndRowBindingsCannotCollideAcrossDevicesOrProfiles() {
        val first = SystemImportPolicy.contactIdentity(source(), raw(), device)
        val otherUserOrDevice = SystemImportPolicy.contactIdentity(source(), raw(), "fedcba9876543210")
        assertEquals("device-raw-id", first.kind)
        assertNotEquals(first.recordId, otherUserOrDevice.recordId); assertNotEquals(first.rowBinding, otherUserOrDevice.rowBinding)
        assertEquals(first, SystemImportPolicy.contactIdentity(source(), raw().copy(version = "5", name = "Updated name"), device.uppercase()))
        for (missing in listOf(null, "", "device", "1".repeat(17)))
            failedWith("provider_unavailable") { SystemImportPolicy.contactIdentity(source(), raw(), missing) }
        failedWith("record_limit") { SystemImportPolicy.contactIdentity(source(), raw(sourceId = "s".repeat(8193)), device) }
    }

    @Test fun aNewSourceIdentityKeepsTheRowBindingForExplicitConflictHandling() {
        val local = SystemImportPolicy.contactIdentity(source(), raw(), device)
        val assigned = SystemImportPolicy.contactIdentity(source(), raw(sourceId = "assigned-by-sync-adapter"), device)
        val reused = SystemImportPolicy.contactIdentity(source(), raw(sourceId = "another-person"), device)
        assertNotEquals(local.recordId, assigned.recordId); assertEquals(local.rowBinding, assigned.rowBinding)
        assertNotEquals(assigned.recordId, reused.recordId); assertEquals(assigned.rowBinding, reused.rowBinding)
    }

    @Test fun contactReadBindsIdentityAndVersionInBothProviderSnapshots() {
        val request = SystemImportRequest.parse(message())
        val first = raw(sourceId = "first-source", backupId = "first-backup")
        for (changed in listOf(first.copy(sourceId = "other-source"), first.copy(backupId = "other-backup"),
            first.copy(version = "2"), first.copy(id = "42"))) {
            var snapshots = 0; var detailReads = 0
            failedWith("provider_changed") {
                SystemImportPolicy.readContacts(request, device,
                    { listOf(if (snapshots++ == 0) first else changed) },
                    { detailReads++; mapOf(first.id to emptyList()) }, {})
            }
            assertEquals(2, snapshots); assertEquals(1, detailReads)
        }
    }

    @Test fun contactReadStopsAfterCancellationInsteadOfReturningACompletedCandidate() {
        var cancelled = false; var snapshots = 0
        failedWith("provider_timeout") {
            SystemImportPolicy.readContacts(SystemImportRequest.parse(message()), device,
                { snapshots++; listOf(raw()) },
                { cancelled = true; mapOf("7" to emptyList()) },
                { check(!cancelled) { "provider_timeout" } })
        }
        assertEquals(1, snapshots)
    }

    @Test fun contactReadPropagatesPermissionRevocationBeforeTheSecondSnapshot() {
        var snapshots = 0
        try {
            SystemImportPolicy.readContacts(SystemImportRequest.parse(message()), device,
                { if (++snapshots == 2) throw SecurityException("permission_required"); listOf(raw()) },
                { mapOf("7" to emptyList()) }, {})
            fail("Permission revocation must reject the candidate")
        } catch (error: SecurityException) { assertEquals("permission_required", error.message) }
        assertEquals(2, snapshots)
    }

    @Test fun duplicateProviderSourceIdentitiesRejectTheWholeRead() {
        val snapshot = listOf(raw(sourceId = "same-source"), raw("42", "same-source"))
        failedWith("provider_changed") {
            SystemImportPolicy.readContacts(SystemImportRequest.parse(message()), device,
                { snapshot }, { mapOf("7" to emptyList(), "42" to emptyList()) }, {})
        }
    }

    @Test fun contactResultCarriesOnlyHashedIdentityMetadataAndCannotOmitItsSelectedRows() {
        val request = SystemImportRequest.parse(message())
        val snapshot = listOf(raw(sourceId = "source-secret-test", backupId = "backup-secret-test"))
        val result = SystemImportPolicy.readContacts(request, device, { snapshot }, { mapOf("7" to emptyList()) }, {})
        assertEquals(2, result.getInt("identitySchema"))
        val record = result.getJSONArray("records").getJSONObject(0)
        assertEquals("source-id", record.getString("identityKind"))
        assertTrue(record.getString("rowBinding").matches(Regex("android-contact-row:[0-9a-f]{64}")))
        assertEquals(record.getString("recordId"), record.getJSONObject("data").getString("uid"))
        assertFalse(result.toString().contains(device)); assertFalse(result.toString().contains("secret-test"))
        failedWith("provider_changed") {
            SystemImportPolicy.readContacts(request, device, { snapshot }, { emptyMap() }, {})
        }
    }

    @Test fun movingOneTimeEventKeepsItsDeviceScopedIdentityWithoutUsingItsBeginTime() {
        val original = instance("2030-04-01T10:00:00Z", "2030-04-01T11:00:00Z")
        val moved = original.copy(begin = millis("2030-04-02T12:00:00Z"), end = millis("2030-04-02T13:00:00Z"))
        assertEquals("single-event", eventIdentity(original).kind)
        assertEquals(eventIdentity(original), eventIdentity(moved))
        assertEquals("2030-04-02", calendar(moved).getString("datum"))
        assertNotEquals(eventIdentity(original), eventIdentity(original.copy(eventId = "18")))
        assertNotEquals(eventIdentity(original), SystemImportPolicy.eventIdentity(source(events), original, "fedcba9876543210"))
        assertNotEquals(eventIdentity(original), SystemImportPolicy.eventIdentity(SystemSourcePolicy.uid(events, "other-calendar"), original, device))
    }

    @Test fun recurringInstancesRemainDistinctAndTheirMovedExceptionKeepsTheOriginalSlot() {
        val original = instance("2030-04-01T10:00:00Z", "2030-04-01T11:00:00Z").copy(recurrenceRule = "FREQ=DAILY")
        val next = original.copy(begin = original.begin + SystemImportWindow.DAY, end = original.end + SystemImportWindow.DAY)
        val moved = original.copy(eventId = "42", begin = original.begin + 7200000, end = original.end + 7200000,
            recurrenceRule = null, originalId = "17", originalInstanceTime = original.begin, originalAllDay = false)
        assertEquals("recurring-instance", eventIdentity(original).kind)
        assertNotEquals(eventIdentity(original), eventIdentity(next))
        assertEquals(eventIdentity(original), eventIdentity(moved))
        assertEquals(eventIdentity(moved), eventIdentity(moved.copy(eventId = "43", begin = moved.begin + 3600000, end = moved.end + 3600000)))
        assertEquals("12:00", calendar(moved).getString("zeit"))
        assertEquals("none", calendar(moved).getJSONObject("wiederholung").getString("art"))
    }

    @Test fun recurrenceDatesUseTheSameInstanceIdentityAsRecurrenceRules() {
        val original = instance().copy(recurrenceRule = "FREQ=DAILY")
        val dates = original.copy(recurrenceRule = null, recurrenceDates = "20300401T100037Z")
        assertEquals(eventIdentity(original), eventIdentity(dates))
        assertNotEquals(eventIdentity(original), eventIdentity(original.copy(recurrenceRule = null)))
    }

    @Test fun movedAllDayExceptionKeepsOriginalUtcDateIdentityAndActualExclusiveEnd() {
        val original = instance("2030-04-01T00:00:00Z", "2030-04-02T00:00:00Z", true).copy(recurrenceRule = "FREQ=WEEKLY")
        val moved = original.copy(eventId = "42", begin = millis("2030-04-03T00:00:00Z"), end = millis("2030-04-05T00:00:00Z"),
            recurrenceRule = null, originalId = "17", originalInstanceTime = original.begin, originalAllDay = true)
        assertEquals(eventIdentity(original), eventIdentity(moved))
        val data = calendar(moved)
        assertEquals("2030-04-03", data.getString("datum")); assertEquals("2030-04-04", data.getString("endDatum"))
        assertEquals("DTEND;VALUE=DATE:20300405", data.getJSONArray("icsRoundtrip").getString(1))
        failedWith("provider_unavailable") { eventIdentity(moved.copy(originalInstanceTime = original.begin + 3600000)) }
    }

    @Test fun unresolvedOrContradictoryRecurrenceExceptionsCannotInventAnIdentity() {
        val base = instance()
        for (invalid in listOf(base.copy(originalId = "3"), base.copy(originalInstanceTime = base.begin),
            base.copy(originalSyncId = "parent-only-on-server"),
            base.copy(originalId = "3", originalInstanceTime = base.begin, recurrenceRule = "FREQ=DAILY"),
            base.copy(originalId = "3", originalInstanceTime = base.begin, recurrenceDates = "20300401T100037Z"),
            base.copy(originalId = "invalid", originalInstanceTime = base.begin),
            base.copy(originalId = base.eventId, originalInstanceTime = base.begin),
            base.copy(originalId = "3", originalInstanceTime = Long.MIN_VALUE)))
            failedWith("provider_unavailable") { eventIdentity(invalid) }
        failedWith("record_limit") { eventIdentity(base.copy(recurrenceRule = "r".repeat(65537))) }
        for (missing in listOf(null, "", "not-an-android-id"))
            failedWith("provider_unavailable") { SystemImportPolicy.eventIdentity(source(events), base, missing) }
    }

    @Test fun eventResultDeclaresIdentitySchemaAndKindWithoutAContactRowBinding() {
        val value = instance(); val identity = eventIdentity(value); val data = calendar(value)
        val batch = SystemImportPolicy.Batch(SystemImportRequest.parse(message(events)))
        batch.add(identity.recordId, data, identity)
        val result = batch.result(); val record = result.getJSONArray("records").getJSONObject(0)
        assertEquals(2, result.getInt("identitySchema")); assertEquals("single-event", record.getString("identityKind"))
        assertFalse(record.has("rowBinding")); assertFalse(result.toString().contains(device))
        rejected { SystemImportPolicy.Batch(SystemImportRequest.parse(message(events))).add(identity.recordId, data) }
        rejected { SystemImportPolicy.Batch(SystemImportRequest.parse(message())).add(identity.recordId, data, identity) }
    }
}
