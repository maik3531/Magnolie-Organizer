package io.gitlab.maik3531.magnolietabletbeta

import android.Manifest
import android.app.Instrumentation
import android.content.ContentUris
import android.content.ContentValues
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.OperationCanceledException
import android.provider.CalendarContract
import android.provider.CalendarContract.Calendars
import android.provider.CalendarContract.Events
import android.provider.ContactsContract
import android.provider.ContactsContract.CommonDataKinds
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.UUID

/**
 * Real API34 providers, synthetic rows, production discovery/read path. Refs #791/#799/#800/#807.
 * No Activity, permission dialog, live revocation, UI Save-ACK or synchronization acceptance.
 * Only fixture writes adopt shell permissions; every product call runs after an explicit drop
 * and an effective-permission check. No hidden UiAutomation APIs or provider mocks are used.
 */
internal object NativeSystemProviderSmoke {
    fun run(instrumentation: Instrumentation, evidence: File, passed: (String, Any) -> Unit): JSONObject =
        Probe(instrumentation, evidence, passed).run()

    private class Probe(private val instrumentation: Instrumentation, private val evidence: File,
                        private val passed: (String, Any) -> Unit) {
        private val context = instrumentation.targetContext
        private val resolver = context.contentResolver
        private val automation get() = instrumentation.uiAutomation
        private val contacts = SystemSourcePolicy.Kind.CONTACTS
        private val events = SystemSourcePolicy.Kind.EVENTS
        private val token = UUID.randomUUID().toString()
        private val account = "magnolie-provider-fixture-$token"
        private val seriesSyncId = "fixture-series-$token"
        private val exceptionSyncId = "fixture-exception-$token"
        private val rawIds = linkedSetOf<Long>()
        private val calendarIds = linkedSetOf<Long>()
        private var fixtureIdentityActive = false
        private var readsGranted = false
        private var completed = false
        private val checks = JSONArray()
        private val permissionChecks = JSONArray()
        private val receipt = JSONObject().put("stage", "system-records").put("sdk", Build.VERSION.SDK_INT)
            .put("syntheticFixtures", true).put("productProviderWrites", false)
            .put("contactsSourceIsolationTested", false).put("calendarSourceIsolationTested", true)
            .put("recurrenceFixtureUsesSyncMetadata", true).put("unsyncedLocalRecurrenceExceptionsTested", false)
            .put("permissionDialogsTested", false).put("livePermissionRevocationTested", false)
            .put("saveAckTested", false).put("inFlightCancellationTested", false)
            .put("checks", checks).put("productPermissionChecks", permissionChecks)
        private var localName: String? = null
        private var localType: String? = null
        private val day = instant("2030-04-01T00:00:00Z")
        private val hour = 3_600_000L
        private val dayLength = 24 * hour

        fun run(): JSONObject {
            check(Build.VERSION.SDK_INT == 34) { "system-records requires the explicit API34 target" }
            check(DisposableEmulatorPolicy.accepts(Build.FINGERPRINT, Build.MODEL, Build.BRAND)) {
                "Disposable emulator required"
            }
            var failure: Throwable? = null
            try {
                // A fresh owned AVD installs without -g. Existing grants are a failed precondition,
                // not a reason to revoke a permission and kill the instrumented process mid-test.
                product("initial-permissions") { Unit }
                localName = RawContacts.getLocalAccountName(context)
                localType = RawContacts.getLocalAccountType(context)
                check((localName == null) == (localType == null)) { "Invalid local contact account pair" }
                lateinit var seed: Seed
                fixtureWrites {
                    val firstRaw = insertContact("primary", "source-$token")
                    insertContact("anchor", "anchor-$token") // Makes raw-row recreation independently observable.
                    val calendar = insertCalendar("selected")
                    val otherCalendar = insertCalendar("unselected")
                    val single = insertEvent(calendar, "single", day + 8 * hour, day + 9 * hour)
                    insertEvent(calendar, "at-from", day - 2 * hour, day - hour)
                    insertEvent(calendar, "ends-at-from", day - 3 * hour, day - 2 * hour)
                    insertEvent(calendar, "starts-at-to", day + 22 * hour, day + 23 * hour)
                    insertEvent(calendar, "all-day", day, day + dayLength, true)
                    insertEvent(calendar, "previous-day", day - dayLength, day, true)
                    insertEvent(calendar, "next-day", day + dayLength, day + 2 * dayLength, true)
                    insertEvent(calendar, "multi-day", day - dayLength, day + 2 * dayLength, true)
                    insertEvent(otherCalendar, "unselected-calendar", day + 8 * hour, day + 9 * hour)
                    val recurring = insertRecurring(calendar)
                    seed = Seed(firstRaw, calendar, otherCalendar, single, recurring)
                }
                val contactSource = SystemSourcePolicy.uid(contacts, "contacts", localType, localName, null)
                val calendarSource = calendarSource(seed.calendar)
                val contactRequest = request(contacts, contactSource)
                val calendarRequest = request(events, calendarSource)
                product("denied-discovery") {
                    AndroidSystemSources.Control().use { control ->
                        val snapshots = AndroidSystemSources(context).status(control)
                        for (kind in listOf(contacts, events)) {
                            check(snapshots[kind]?.state == "not_granted" && snapshots[kind]?.sources == null)
                        }
                    }
                }
                for (request in listOf(contactRequest, calendarRequest)) {
                    expect<SecurityException>("denied-${request.kind.wire}") { read(request, "denied-${request.kind.wire}") }
                }
                record("real provider reads require runtime READ permissions")
                for (permission in readPermissions) automation.grantRuntimePermission(context.packageName, permission)
                readsGranted = true
                verifyContactRow(seed.raw, "source-$token")
                product("authorized-discovery") {
                    AndroidSystemSources.Control().use { control ->
                        val snapshots = AndroidSystemSources(context).status(control)
                        for ((kind, source) in listOf(contacts to contactSource, events to calendarSource,
                            events to calendarSource(seed.otherCalendar))) {
                            val snapshot = snapshots.getValue(kind)
                            check(snapshot.state == "authorized" && snapshot.sources!!.any { it.uid == source })
                        }
                    }
                }
                record("real discovery finds the local contact source and both fixture calendars")

                val beforeContact = contact(read(contactRequest, "contact-before"))
                check(beforeContact.getString("identityKind") == "source-id")
                val contactData = beforeContact.getJSONObject("data")
                check(contactData.getString("vorname") == "TabletFixture" && contactData.getString("nachname") == "primary")
                check(contactData.getString("geburtstag") == "2000-02-29")
                val phone = contactData.getJSONArray("telefone").getJSONObject(0)
                check(phone.getString("wert") == "+491555010100" && phone.getJSONArray("typen").getString(0) == "HOME")
                record("real contact Data rows project name, phone type and birthday")
                val recreated = fixtureWrites {
                    deleteContact(seed.raw)
                    insertContact("primary", "source-$token")
                }
                check(recreated != seed.raw) { "Fixture did not create a different RawContacts row" }
                verifyContactRow(recreated, "source-$token")
                val afterContact = contact(read(contactRequest, "contact-recreated"))
                check(beforeContact.getString("recordId") == afterContact.getString("recordId"))
                check(beforeContact.getString("rowBinding") != afterContact.getString("rowBinding"))
                record("same SOURCE_ID survives a genuinely different raw row; rowBinding changes")
                fixtureWrites {
                    check(resolver.update(contactUri(recreated), ContentValues().apply {
                        put(RawContacts.SOURCE_ID, "replacement-$token")
                    }, null, null) == 1)
                }
                verifyContactRow(recreated, "replacement-$token")
                val replaced = contact(read(contactRequest, "contact-source-replaced"))
                check(afterContact.getString("recordId") != replaced.getString("recordId"))
                check(afterContact.getString("rowBinding") == replaced.getString("rowBinding"))
                record("changed SOURCE_ID on the same row yields a different record with the same rowBinding")

                val first = records(read(calendarRequest, "calendar-east-window"))
                check(first.map { title(it) }.toSet() == setOf("single", "at-from", "all-day", "multi-day", "series"))
                val allDay = titled(first, "all-day").getJSONObject("data")
                check(allDay.getString("datum") == "2030-04-01" && allDay.getString("zeit") == "" && allDay.getString("endDatum") == "")
                check(strings(allDay.getJSONArray("icsRoundtrip")) == listOf("DTSTART;VALUE=DATE:20300401", "DTEND;VALUE=DATE:20300402"))
                val multi = titled(first, "multi-day").getJSONObject("data")
                check(multi.getString("datum") == "2030-03-31" && multi.getString("endDatum") == "2030-04-02")
                record("selected calendar only; timed half-open bounds and all-day UTC date bounds")
                val west = records(read(request(events, calendarSource, west = true), "calendar-west-window"))
                check(west.any { title(it) == "all-day" } && west.none { title(it) in setOf("previous-day", "next-day", "unselected-calendar") })
                record("all-day selection also keeps the final selected date in a western instant window")
                val singleBefore = titled(first, "single")
                check(singleBefore.getString("identityKind") == "single-event")
                check(singleBefore.getJSONObject("data").getString("zeit") == "08:00")
                fixtureWrites {
                    check(resolver.update(eventUri(seed.single), ContentValues().apply {
                        put(Events.DTSTART, day + 10 * hour); put(Events.DTEND, day + 11 * hour)
                    }, null, null) == 1)
                }
                val singleAfter = titled(records(read(calendarRequest, "single-moved")), "single")
                check(singleBefore.getString("recordId") == singleAfter.getString("recordId"))
                check(singleAfter.getJSONObject("data").getString("zeit") == "10:00")
                record("moving one actual Events row preserves single-event identity")

                val seriesRequest = request(events, calendarSource, twoDays = true)
                val seriesBefore = records(read(seriesRequest, "series-before")).filter { title(it) == "series" }
                val seriesProof = JSONObject().put("linkage", "synthetic-sync-adapter")
                    .put("beforeCount", seriesBefore.size)
                receipt.put("recurringException", seriesProof)
                seriesProof.put("before", seriesSlots(seriesBefore))
                check(seriesBefore.size == 2 && seriesBefore.all { it.getString("identityKind") == "recurring-instance" })
                val original = seriesBefore.single { it.getJSONObject("data").getString("datum") == "2030-04-01" }
                val unchanged = seriesBefore.single { it.getJSONObject("data").getString("datum") == "2030-04-02" }
                val exceptionId = fixtureWrites { insertException(seed.calendar, seed.recurring) }
                check(exceptionId != seed.recurring)
                verifySeriesRows(seed.calendar, seed.recurring, exceptionId, seriesProof)
                val seriesAfter = records(read(seriesRequest, "series-exception")).filter { title(it) == "series" }
                seriesProof.put("afterCount", seriesAfter.size).put("after", seriesSlots(seriesAfter))
                check(seriesAfter.size == 2) { "Provider must replace the original recurring slot and retain the second slot; actual=${seriesAfter.size}" }
                val moved = seriesAfter.single { it.getJSONObject("data").getString("datum") == "2030-04-01" }
                check(moved.getString("identityKind") == "recurring-instance" && moved.getString("recordId") == original.getString("recordId"))
                check(moved.getJSONObject("data").getString("zeit") == "12:00")
                check(seriesAfter.single { it.getJSONObject("data").getString("datum") == "2030-04-02" }.getString("recordId") == unchanged.getString("recordId"))
                record("real RRULE expansion and moved exception preserve the original instance identity")

                for (request in listOf(contactRequest, calendarRequest)) {
                    expect<OperationCanceledException>("cancelled-${request.kind.wire}") {
                        read(request, "cancelled-${request.kind.wire}", cancelled = true)
                    }
                }
                record("Android CancellationSignal rejects both reads before querying")
                completed = true
            } catch (error: Throwable) {
                failure = error
                receipt.put("failureClass", error.javaClass.simpleName)
                throw error
            } finally {
                try {
                    cleanup()
                } catch (cleanup: Throwable) {
                    completed = false
                    receipt.put("cleanupFailureClass", cleanup.javaClass.simpleName)
                    if (failure != null) failure.addSuppressed(cleanup) else throw cleanup
                } finally {
                    receipt.put("passed", completed && failure == null)
                    evidence.writeText(receipt.toString(2) + "\n")
                }
            }
            return receipt
        }

        private data class Seed(val raw: Long, val calendar: Long, val otherCalendar: Long, val single: Long, val recurring: Long)
        private val writePermissions = listOf(Manifest.permission.WRITE_CONTACTS, Manifest.permission.WRITE_CALENDAR)
        private val readPermissions = listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.READ_CALENDAR)
        private fun granted(permission: String) = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

        private fun assertNoFixtureIdentity() {
            check(!fixtureIdentityActive) { "Fixture identity must never reach a product read" }
            check(writePermissions.none(::granted)) { "Effective fixture WRITE permission is still present" }
        }

        private fun <T> product(label: String, block: () -> T): T {
            check(!fixtureIdentityActive) { "Fixture permission scope still active" }
            // There is no public SDK getter for adopted permissions. Explicitly drop and prove
            // the two permissions this fixture can adopt are no longer effective (CTS pattern).
            automation.dropShellPermissionIdentity()
            assertNoFixtureIdentity()
            check(readPermissions.all { granted(it) == readsGranted }) { "Unexpected READ permission state" }
            permissionChecks.put(JSONObject().put("operation", label).put("dropShellPermissionIdentityCompleted", true)
                .put("fixtureScopeActive", false).put("writeContacts", false).put("writeCalendar", false)
                .put("readContacts", granted(Manifest.permission.READ_CONTACTS))
                .put("readCalendar", granted(Manifest.permission.READ_CALENDAR)))
            return block()
        }

        private fun <T> fixtureWrites(block: () -> T): T {
            check(!fixtureIdentityActive)
            fixtureIdentityActive = true
            try {
                automation.adoptShellPermissionIdentity(*writePermissions.toTypedArray())
                check(writePermissions.all(::granted)) { "Fixture WRITE delegation failed" }
                return block()
            } finally {
                automation.dropShellPermissionIdentity()
                fixtureIdentityActive = false // A failed drop cannot clear this guard.
                assertNoFixtureIdentity()
            }
        }

        private fun record(name: String) {
            checks.put(name)
            evidence.writeText(receipt.toString(2) + "\n")
            passed(name, true)
        }

        private inline fun <reified T : Throwable> expect(label: String, block: () -> Unit) {
            try { block() } catch (error: Throwable) {
                check(error is T) { "$label raised ${error.javaClass.simpleName}, expected ${T::class.java.simpleName}" }
                return
            }
            error("$label unexpectedly succeeded")
        }

        private fun request(kind: SystemSourcePolicy.Kind, source: String, west: Boolean = false, twoDays: Boolean = false): SystemImportRequest {
            val value = JSONObject().put("cmd", SystemImportRequest.COMMAND).put("art", kind.wire)
                .put("sourceUid", source).put("requestId", UUID.randomUUID().toString())
                .put("session", "synthetic-provider-$token").put("revision", "synthetic-provider-revision")
            if (kind == events) {
                val offset = if (west) 7 * hour else -2 * hour
                value.put("from", day + offset).put("to", day + (if (twoDays) 2 else 1) * dayLength + offset)
                    .put("dateFrom", "2030-04-01").put("dateTo", if (twoDays) "2030-04-02" else "2030-04-01")
            }
            return SystemImportRequest.parse(value)
        }

        private fun read(request: SystemImportRequest, label: String, cancelled: Boolean = false): JSONObject = product(label) {
            AndroidSystemSources.Control().use { control ->
                if (cancelled) control.cancel()
                AndroidSystemRecords(context).read(request, control, ::assertNoFixtureIdentity).also {
                    check(it.getBoolean("ok") && it.getBoolean("complete") && it.getInt("identitySchema") == 2)
                    check(it.getString("sourceUid") == request.sourceUid && it.getString("requestId") == request.requestId)
                }
            }
        }

        private fun records(result: JSONObject): List<JSONObject> = result.getJSONArray("records").let { rows ->
            (0 until rows.length()).map { rows.getJSONObject(it) }
        }
        private fun contact(result: JSONObject) = records(result).single {
            it.getJSONObject("data").optString("vorname") == "TabletFixture" &&
                it.getJSONObject("data").optString("nachname") == "primary"
        }
        private fun title(record: JSONObject) = record.getJSONObject("data").getString("titel")
        private fun titled(records: List<JSONObject>, title: String) = records.single { title(it) == title }
        private fun strings(array: JSONArray) = (0 until array.length()).map(array::getString)
        private fun seriesSlots(records: List<JSONObject>): JSONArray {
            check(records.size <= 8) { "Unexpected number of synthetic series slots" }
            return JSONArray(records.map { record ->
                val data = record.getJSONObject("data")
                JSONObject().put("recordId", record.getString("recordId")).put("identityKind", record.getString("identityKind"))
                    .put("date", data.getString("datum")).put("time", data.getString("zeit"))
                    .put("endDate", data.getString("endDatum")).put("endTime", data.getString("endZeit"))
            })
        }
        private fun instant(text: String) = Instant.parse(text).toEpochMilli()
        private fun calendarSource(id: Long) = SystemSourcePolicy.uid(events, "calendar", CalendarContract.ACCOUNT_TYPE_LOCAL, account, id.toString())

        private fun contactUri(id: Long): Uri = ContentUris.withAppendedId(RawContacts.CONTENT_URI, id).buildUpon()
            .appendQueryParameter(ContactsContract.CALLER_IS_SYNCADAPTER, "true").build()
        private fun calendarUri(id: Long? = null): Uri = (id?.let { ContentUris.withAppendedId(Calendars.CONTENT_URI, it) }
            ?: Calendars.CONTENT_URI).buildUpon().appendQueryParameter(CalendarContract.CALLER_IS_SYNCADAPTER, "true")
            .appendQueryParameter(Calendars.ACCOUNT_NAME, account).appendQueryParameter(Calendars.ACCOUNT_TYPE, CalendarContract.ACCOUNT_TYPE_LOCAL).build()
        private fun eventUri(id: Long? = null): Uri = (id?.let { ContentUris.withAppendedId(Events.CONTENT_URI, it) }
            ?: Events.CONTENT_URI).buildUpon().appendQueryParameter(CalendarContract.CALLER_IS_SYNCADAPTER, "true")
            .appendQueryParameter(Calendars.ACCOUNT_NAME, account).appendQueryParameter(Calendars.ACCOUNT_TYPE, CalendarContract.ACCOUNT_TYPE_LOCAL).build()

        private fun insertContact(label: String, sourceId: String): Long {
            val uri = RawContacts.CONTENT_URI.buildUpon().appendQueryParameter(ContactsContract.CALLER_IS_SYNCADAPTER, "true").build()
            val id = ContentUris.parseId(checkNotNull(resolver.insert(uri, ContentValues().apply {
                put(RawContacts.ACCOUNT_NAME, localName); put(RawContacts.ACCOUNT_TYPE, localType)
                putNull(RawContacts.DATA_SET); put(RawContacts.SOURCE_ID, sourceId)
                put(RawContacts.BACKUP_ID, "backup-$label-$token")
            })))
            check(id > 0); check(rawIds.add(id))
            fun data(mime: String, values: ContentValues) {
                values.put(Data.RAW_CONTACT_ID, id); values.put(Data.MIMETYPE, mime)
                checkNotNull(resolver.insert(Data.CONTENT_URI, values))
            }
            data(CommonDataKinds.StructuredName.CONTENT_ITEM_TYPE, ContentValues().apply {
                put(CommonDataKinds.StructuredName.GIVEN_NAME, "TabletFixture")
                put(CommonDataKinds.StructuredName.FAMILY_NAME, label)
            })
            data(CommonDataKinds.Phone.CONTENT_ITEM_TYPE, ContentValues().apply {
                put(CommonDataKinds.Phone.NUMBER, "+491555010100"); put(CommonDataKinds.Phone.TYPE, CommonDataKinds.Phone.TYPE_HOME)
            })
            data(CommonDataKinds.Event.CONTENT_ITEM_TYPE, ContentValues().apply {
                put(CommonDataKinds.Event.START_DATE, "2000-02-29"); put(CommonDataKinds.Event.TYPE, CommonDataKinds.Event.TYPE_BIRTHDAY)
            })
            return id
        }

        private fun verifyContactRow(id: Long, sourceId: String) = product("fixture-contact-readback") {
            val columns = arrayOf(RawContacts.ACCOUNT_NAME, RawContacts.ACCOUNT_TYPE, RawContacts.DATA_SET, RawContacts.SOURCE_ID, RawContacts.BACKUP_ID)
            checkNotNull(resolver.query(ContentUris.withAppendedId(RawContacts.CONTENT_URI, id), columns, null, null, null)).use { cursor ->
                check(cursor.moveToFirst())
                fun text(index: Int) = if (cursor.isNull(index)) null else cursor.getString(index)
                check(text(0) == localName && text(1) == localType && text(2) == null && text(3) == sourceId)
                check(text(4) == "backup-primary-$token" && !cursor.moveToNext())
            }
        }

        private fun insertCalendar(label: String): Long {
            val id = ContentUris.parseId(checkNotNull(resolver.insert(calendarUri(), ContentValues().apply {
                put(Calendars.ACCOUNT_NAME, account); put(Calendars.ACCOUNT_TYPE, CalendarContract.ACCOUNT_TYPE_LOCAL)
                put(Calendars.NAME, "$account-$label"); put(Calendars.CALENDAR_DISPLAY_NAME, "Tablet fixture $label")
                put(Calendars.CALENDAR_COLOR, 0xff406080.toInt()); put(Calendars.CALENDAR_ACCESS_LEVEL, Calendars.CAL_ACCESS_OWNER)
                put(Calendars.OWNER_ACCOUNT, "$account@example.invalid"); put(Calendars.VISIBLE, 1); put(Calendars.SYNC_EVENTS, 1)
                put(Calendars.CALENDAR_TIME_ZONE, "UTC")
            })))
            check(id > 0); check(calendarIds.add(id))
            return id
        }

        private fun insertEvent(calendar: Long, title: String, begin: Long, end: Long, allDay: Boolean = false): Long =
            insertEventValues(ContentValues().apply {
                put(Events.CALENDAR_ID, calendar); put(Events.TITLE, title); put(Events.DTSTART, begin); put(Events.DTEND, end)
                put(Events.ALL_DAY, if (allDay) 1 else 0); put(Events.EVENT_TIMEZONE, "UTC"); put(Events.STATUS, Events.STATUS_CONFIRMED)
            })

        private fun insertRecurring(calendar: Long): Long = insertEventValues(ContentValues().apply {
            put(Events.CALENDAR_ID, calendar); put(Events.TITLE, "series"); put(Events.DTSTART, day + 9 * hour)
            // The fixture already writes as a sync adapter. Supply its complete synthetic
            // linkage: AOSP14 re-expands exceptions through _SYNC_ID/ORIGINAL_SYNC_ID (#807).
            // This does not test the provider's separate unsynced-local-exception path.
            put(Events._SYNC_ID, seriesSyncId)
            put(Events.DURATION, "PT1H"); put(Events.RRULE, "FREQ=DAILY;COUNT=2")
            put(Events.ALL_DAY, 0); put(Events.EVENT_TIMEZONE, "UTC"); put(Events.STATUS, Events.STATUS_CONFIRMED)
        })

        private fun insertException(calendar: Long, parent: Long): Long = insertEventValues(ContentValues().apply {
            put(Events.CALENDAR_ID, calendar); put(Events.TITLE, "series")
            put(Events._SYNC_ID, exceptionSyncId); put(Events.ORIGINAL_SYNC_ID, seriesSyncId)
            put(Events.DTSTART, day + 12 * hour); put(Events.DTEND, day + 13 * hour)
            put(Events.ORIGINAL_ID, parent); put(Events.ORIGINAL_INSTANCE_TIME, day + 9 * hour); put(Events.ORIGINAL_ALL_DAY, 0)
            put(Events.ALL_DAY, 0); put(Events.EVENT_TIMEZONE, "UTC"); put(Events.STATUS, Events.STATUS_CONFIRMED)
        })

        private fun verifySeriesRows(calendar: Long, parent: Long, exception: Long, proof: JSONObject) = product("fixture-series-readback") {
            check(calendar in calendarIds)
            val columns = arrayOf(Events._ID, Events.CALENDAR_ID, Events._SYNC_ID, Events.ORIGINAL_ID, Events.ORIGINAL_SYNC_ID,
                Events.ORIGINAL_INSTANCE_TIME, Events.ORIGINAL_ALL_DAY, Events.DTSTART, Events.DTEND, Events.DURATION,
                Events.RRULE, Events.RDATE, Events.ALL_DAY, Events.EVENT_TIMEZONE, Events.STATUS)
            val rows = JSONArray()
            proof.put("providerEvents", rows)
            AndroidSystemSources.Control().use { control ->
                checkNotNull(resolver.query(Events.CONTENT_URI, columns,
                    Events.CALENDAR_ID + "=? AND " + Events._ID + " IN (?,?)",
                    arrayOf(calendar.toString(), parent.toString(), exception.toString()), Events._ID + " ASC", control.signal)).use { cursor ->
                    while (cursor.moveToNext()) {
                        control.check(); check(rows.length() < 2)
                        val row = JSONObject()
                        for (index in columns.indices) {
                            val value = if (cursor.isNull(index)) null else cursor.getString(index)
                            check(value == null || value.length <= 1024)
                            row.put(columns[index], value ?: JSONObject.NULL)
                        }
                        rows.put(row)
                    }
                }
            }
            check(rows.length() == 2) { "Both fixture-owned series Events rows must exist" }
            fun row(id: Long) = (0 until rows.length()).map(rows::getJSONObject).single { it.getString(Events._ID) == id.toString() }
            val master = row(parent); val moved = row(exception)
            check(master.getString(Events._SYNC_ID) == seriesSyncId && master.getString(Events.RRULE) == "FREQ=DAILY;COUNT=2")
            check(master.getString(Events.DURATION) == "PT1H" && master.isNull(Events.DTEND))
            check(moved.getString(Events._SYNC_ID) == exceptionSyncId && moved.getString(Events.ORIGINAL_SYNC_ID) == seriesSyncId)
            check(moved.getString(Events.ORIGINAL_ID) == parent.toString() && moved.getLong(Events.ORIGINAL_INSTANCE_TIME) == day + 9 * hour)
            check(moved.getInt(Events.ORIGINAL_ALL_DAY) == 0 && moved.isNull(Events.RRULE) && moved.isNull(Events.RDATE) && moved.isNull(Events.DURATION))
            check(moved.getLong(Events.DTSTART) == day + 12 * hour && moved.getLong(Events.DTEND) == day + 13 * hour)
            for (item in listOf(master, moved)) {
                check(item.getString(Events.CALENDAR_ID) == calendar.toString() && item.getInt(Events.ALL_DAY) == 0)
                check(item.getString(Events.EVENT_TIMEZONE) == "UTC" && item.getInt(Events.STATUS) == Events.STATUS_CONFIRMED)
            }
        }

        private fun insertEventValues(values: ContentValues): Long {
            check(values.getAsLong(Events.CALENDAR_ID) in calendarIds) { "Only fixture-owned calendars may be written" }
            return ContentUris.parseId(checkNotNull(resolver.insert(eventUri(), values))).also { check(it > 0) }
        }

        private fun deleteContact(id: Long) {
            check(id in rawIds)
            check(resolver.delete(contactUri(id), null, null) == 1) { "Fixture contact deletion failed" }
            rawIds.remove(id)
        }

        private fun cleanup() {
            // No account-wide/table-wide deletion: only IDs returned by successful own inserts.
            val rawCount = rawIds.size; val calendarCount = calendarIds.size
            var failure: Throwable? = null
            fixtureWrites {
                fun attempt(block: () -> Unit) {
                    try { block() } catch (error: Throwable) {
                        if (failure == null) failure = error else failure!!.addSuppressed(error)
                    }
                }
                for (id in rawIds.toList()) attempt { deleteContact(id) }
                for (id in calendarIds.toList()) attempt {
                    check(resolver.delete(calendarUri(id), null, null) == 1) { "Fixture calendar deletion failed" }
                    calendarIds.remove(id) // Android cascades events belonging to this exact calendar.
                }
            }
            receipt.put("cleanup", JSONObject().put("requestedRawRows", rawCount).put("requestedCalendars", calendarCount)
                .put("remainingOwnedRawRows", rawIds.size).put("remainingOwnedCalendars", calendarIds.size)
                .put("shellIdentityDropped", !fixtureIdentityActive).put("writePermissionsDenied", writePermissions.none(::granted)))
            failure?.let { throw it }
            check(rawIds.isEmpty() && calendarIds.isEmpty())
            record("owned fixture IDs removed; fixture WRITE permissions absent after cleanup")
        }
    }
}
