package io.gitlab.maik3531.magnolietabletbeta

import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.os.Looper
import android.provider.CalendarContract.Calendars
import android.provider.CalendarContract.Events
import android.provider.CalendarContract.Instances
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import android.provider.Settings.Secure
import org.json.JSONObject

/** Explicit read-only import from one provider source. No provider mutation API is used. Refs #791, #799, #800. */
internal class AndroidSystemRecords(private val context: Context) {
    private data class CalendarSource(val id: String, val accountType: String?, val accountName: String?)
    private class Budget {
        private var rows = 0
        private var bytes = 0
        fun row() { check(++rows <= SystemImportPolicy.MAX_ROWS) { "record_limit" } }
        fun text(value: String?): String? = value?.also {
            val size = it.toByteArray(Charsets.UTF_8).size
            check(size <= SystemImportPolicy.MAX_TEXT_BYTES) { "record_limit" }
            bytes += size
            check(bytes <= SystemImportPolicy.MAX_BYTES) { "record_limit" }
        }
    }
    private fun Cursor.text(column: String): String? = getColumnIndexOrThrow(column).let { if (isNull(it)) null else getString(it) }
    private fun checkPermission(kind: SystemSourcePolicy.Kind) {
        if (context.checkSelfPermission(AndroidSystemSources.permission(kind)) != PackageManager.PERMISSION_GRANTED)
            throw SecurityException("permission_required")
    }

    fun read(request: SystemImportRequest, control: AndroidSystemSources.Control, checkCurrent: () -> Unit): JSONObject {
        check(Looper.myLooper() != Looper.getMainLooper()) { "System provider reads require a worker" }
        fun current() { control.check(); checkCurrent(); checkPermission(request.kind) }
        current()
        // A renderer-provided source UID is only a selector. Resolve it again from the real provider.
        fun selectedSource() {
            current()
            val snapshot = AndroidSystemSources(context).status(control, listOf(request.kind))[request.kind]
            if (snapshot?.state == "not_granted") throw SecurityException("permission_required")
            check(snapshot?.state == "authorized") { snapshot?.errorCode ?: "provider_unavailable" }
            check(snapshot.sources.orEmpty().any { it.uid == request.sourceUid }) { "source_unavailable" }
        }
        selectedSource()
        val result = when (request.kind) {
            SystemSourcePolicy.Kind.CONTACTS -> contacts(request, control, ::current)
            SystemSourcePolicy.Kind.EVENTS -> calendar(request, control, ::current)
        }
        selectedSource()
        current()
        return result
    }

    private fun rawContacts(request: SystemImportRequest, control: AndroidSystemSources.Control, current: () -> Unit): List<SystemImportPolicy.RawContact> {
        current()
        val projection = arrayOf(RawContacts._ID, RawContacts.VERSION, RawContacts.DISPLAY_NAME_PRIMARY,
            RawContacts.ACCOUNT_NAME, RawContacts.ACCOUNT_TYPE, RawContacts.DATA_SET, RawContacts.SOURCE_ID, RawContacts.BACKUP_ID)
        val found = ArrayList<SystemImportPolicy.RawContact>()
        val budget = Budget()
        val cursor = context.contentResolver.query(RawContacts.CONTENT_URI, projection,
            RawContacts.DELETED + "=0", null, RawContacts._ID + " ASC", control.signal) ?: error("provider_unavailable")
        cursor.use { while (it.moveToNext()) {
            control.check(); budget.row()
            val source = SystemSourcePolicy.uid(SystemSourcePolicy.Kind.CONTACTS, "contacts",
                it.text(RawContacts.ACCOUNT_TYPE), it.text(RawContacts.ACCOUNT_NAME), it.text(RawContacts.DATA_SET))
            if (source == request.sourceUid) {
                check(found.size < SystemImportPolicy.MAX_RECORDS) { "record_limit" }
                found.add(SystemImportPolicy.RawContact(it.text(RawContacts._ID) ?: error("provider_unavailable"),
                    it.text(RawContacts.VERSION) ?: error("provider_unavailable"),
                    budget.text(it.text(RawContacts.DISPLAY_NAME_PRIMARY)).orEmpty(),
                    budget.text(it.text(RawContacts.SOURCE_ID)), budget.text(it.text(RawContacts.BACKUP_ID))))
            }
        } }
        current()
        check(found.map { it.id }.toSet().size == found.size) { "provider_changed" }
        return found
    }

    private fun contacts(request: SystemImportRequest, control: AndroidSystemSources.Control, current: () -> Unit): JSONObject {
        current()
        val deviceId = Secure.getString(context.contentResolver, Secure.ANDROID_ID)
        return SystemImportPolicy.readContacts(request, deviceId,
            { rawContacts(request, control, current) },
            { before -> contactDetails(before, control, current) }, control::check)
    }

    private fun contactDetails(before: List<SystemImportPolicy.RawContact>, control: AndroidSystemSources.Control,
                               current: () -> Unit): Map<String, List<SystemImportPolicy.Detail>> {
        val details = before.associate { it.id to ArrayList<SystemImportPolicy.Detail>() }
        val budget = Budget()
        val fields = arrayOf(Data.DATA1, Data.DATA2, Data.DATA3, Data.DATA4, Data.DATA5,
            Data.DATA6, Data.DATA7, Data.DATA8, Data.DATA9, Data.DATA10)
        val projection = arrayOf(Data.RAW_CONTACT_ID, Data.MIMETYPE) + fields
        for (batch in before.chunked(100)) {
            current()
            val ids = batch.map { it.id }
            val mimes = SystemImportPolicy.contactMimeTypes
            val selection = Data.RAW_CONTACT_ID + " IN (" + ids.joinToString(",") { "?" } + ") AND " +
                Data.MIMETYPE + " IN (" + mimes.joinToString(",") { "?" } + ")"
            val cursor = context.contentResolver.query(Data.CONTENT_URI, projection, selection,
                (ids + mimes).toTypedArray(), Data.RAW_CONTACT_ID + " ASC," + Data._ID + " ASC", control.signal)
                ?: error("provider_unavailable")
            cursor.use { while (it.moveToNext()) {
                control.check(); budget.row()
                val rawId = it.text(Data.RAW_CONTACT_ID) ?: error("provider_unavailable")
                check(rawId in ids) { "provider_changed" }
                val mime = it.text(Data.MIMETYPE) ?: error("provider_unavailable")
                check(mime in mimes) { "provider_unavailable" }
                val values = fields.map { column -> budget.text(it.text(column)) }
                details.getValue(rawId).add(SystemImportPolicy.Detail(mime, values))
            } }
        }
        current()
        return details
    }

    private fun calendarSource(request: SystemImportRequest, control: AndroidSystemSources.Control, current: () -> Unit): CalendarSource {
        current()
        val projection = arrayOf(Calendars._ID, Calendars.ACCOUNT_TYPE, Calendars.ACCOUNT_NAME)
        val found = ArrayList<CalendarSource>()
        var rows = 0
        val cursor = context.contentResolver.query(Calendars.CONTENT_URI, projection, null, null, Calendars._ID + " ASC", control.signal)
            ?: error("provider_unavailable")
        cursor.use { while (it.moveToNext()) {
            control.check(); check(++rows <= 1000) { "source_limit" }
            val id = it.text(Calendars._ID) ?: error("provider_unavailable")
            val type = it.text(Calendars.ACCOUNT_TYPE); val name = it.text(Calendars.ACCOUNT_NAME)
            if (SystemSourcePolicy.uid(SystemSourcePolicy.Kind.EVENTS, "calendar", type, name, id) == request.sourceUid)
                found.add(CalendarSource(id, type, name))
        } }
        current()
        check(found.size == 1) { "source_unavailable" }
        return found.single()
    }

    private fun instances(request: SystemImportRequest, source: CalendarSource, control: AndroidSystemSources.Control,
                          current: () -> Unit): List<SystemImportPolicy.CalendarInstance> {
        current()
        val window = SystemImportWindow.of(request)
        val builder = Instances.CONTENT_URI.buildUpon()
        ContentUris.appendId(builder, window.queryFrom); ContentUris.appendId(builder, window.queryTo)
        val projection = arrayOf(Instances.EVENT_ID, Instances.BEGIN, Instances.END, Events.ALL_DAY,
            Events.TITLE, Events.DESCRIPTION, Events.EVENT_LOCATION, Events.CALENDAR_ID, Events.STATUS,
            Events.RRULE, Events.RDATE, Events.ORIGINAL_ID, Events.ORIGINAL_INSTANCE_TIME, Events.ORIGINAL_SYNC_ID, Events.ORIGINAL_ALL_DAY)
        val selection = Events.CALENDAR_ID + "=? AND (" + Events.STATUS + " IS NULL OR " + Events.STATUS + "<>?)"
        val cursor = context.contentResolver.query(builder.build(), projection, selection,
            arrayOf(source.id, Events.STATUS_CANCELED.toString()), Instances.BEGIN + " ASC," + Instances.EVENT_ID + " ASC", control.signal)
            ?: error("provider_unavailable")
        val found = ArrayList<SystemImportPolicy.CalendarInstance>()
        val budget = Budget()
        cursor.use { while (it.moveToNext()) {
            control.check(); budget.row()
            check(it.text(Events.CALENDAR_ID) == source.id && it.text(Events.STATUS) != Events.STATUS_CANCELED.toString()) { "provider_changed" }
            val begin = it.text(Instances.BEGIN)?.toLongOrNull() ?: error("provider_unavailable")
            val end = it.text(Instances.END)?.toLongOrNull() ?: error("provider_unavailable")
            val allDay = it.text(Events.ALL_DAY) == "1"
            // Query the union so western zones do not miss date-based instances. Then filter
            // timed instants and all-day UTC date spans separately using their original domains.
            if (window.contains(begin, end, allDay)) {
                check(found.size < SystemImportPolicy.MAX_RECORDS) { "record_limit" }
                val originalTime = it.text(Events.ORIGINAL_INSTANCE_TIME)?.let { value -> value.toLongOrNull() ?: error("provider_unavailable") }
                val originalAllDay = when (it.text(Events.ORIGINAL_ALL_DAY)) {
                    null -> null; "0" -> false; "1" -> true; else -> error("provider_unavailable")
                }
                found.add(SystemImportPolicy.CalendarInstance(it.text(Instances.EVENT_ID) ?: error("provider_unavailable"),
                    begin, end, allDay, budget.text(it.text(Events.TITLE)).orEmpty(),
                    budget.text(it.text(Events.DESCRIPTION)).orEmpty(), budget.text(it.text(Events.EVENT_LOCATION)).orEmpty(),
                    budget.text(it.text(Events.RRULE)), budget.text(it.text(Events.RDATE)), budget.text(it.text(Events.ORIGINAL_ID)),
                    originalTime, budget.text(it.text(Events.ORIGINAL_SYNC_ID)), originalAllDay))
            }
        } }
        current()
        return found
    }

    private fun calendar(request: SystemImportRequest, control: AndroidSystemSources.Control, current: () -> Unit): JSONObject {
        current()
        val deviceId = Secure.getString(context.contentResolver, Secure.ANDROID_ID)
        val source = calendarSource(request, control, current)
        val first = instances(request, source, control, current)
        // CalendarContract exposes no general collection revision. Two equal bounded reads
        // are required; this is an import observation, never an atomic synchronization claim.
        check(first == instances(request, source, control, current)) { "provider_changed" }
        check(source == calendarSource(request, control, current)) { "provider_changed" }
        val output = SystemImportPolicy.Batch(request)
        for (instance in first) {
            control.check()
            val identity = SystemImportPolicy.eventIdentity(request.sourceUid, instance, deviceId)
            val data = SystemImportPolicy.calendar(identity, instance)
            output.add(identity.recordId, data, identity)
        }
        return output.result()
    }
}
