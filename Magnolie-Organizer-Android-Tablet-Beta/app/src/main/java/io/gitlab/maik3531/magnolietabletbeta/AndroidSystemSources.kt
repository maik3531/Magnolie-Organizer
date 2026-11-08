package io.gitlab.maik3531.magnolietabletbeta

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.os.CancellationSignal
import android.os.Looper
import android.os.SystemClock
import android.provider.CalendarContract.Calendars
import android.provider.ContactsContract.RawContacts
import android.provider.ContactsContract.Settings
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Queue-independent read-only public provider discovery. Never reads credentials or item bodies. */
internal class AndroidSystemSources(private val context: Context) {
    class Control : AutoCloseable {
        val signal=CancellationSignal()
        private val deadline=SystemClock.elapsedRealtime()+15_000
        private val timer=timeouts.schedule({signal.cancel()},15,TimeUnit.SECONDS)
        fun cancel()=signal.cancel()
        fun check() { signal.throwIfCanceled(); check(SystemClock.elapsedRealtime()<deadline) { "provider_timeout" } }
        override fun close() { timer.cancel(false) }
    }
    companion object {
        private val timeouts=Executors.newSingleThreadScheduledExecutor { task -> Thread(task,"system-source-deadline").apply {isDaemon=true} }
        fun permission(kind: SystemSourcePolicy.Kind)=when(kind) {
            SystemSourcePolicy.Kind.EVENTS -> Manifest.permission.READ_CALENDAR
            SystemSourcePolicy.Kind.CONTACTS -> Manifest.permission.READ_CONTACTS
        }
    }
    fun status(control: Control): Map<SystemSourcePolicy.Kind,SystemSourcePolicy.Snapshot> {
        check(Looper.myLooper()!=Looper.getMainLooper()) { "System provider reads require a worker" }
        return SystemSourcePolicy.Kind.entries.associateWith { kind ->
            control.check()
            SystemSourcePolicy.discover(context.checkSelfPermission(permission(kind))==PackageManager.PERMISSION_GRANTED,
                control::check) {
                when(kind) { SystemSourcePolicy.Kind.EVENTS -> calendars(control); SystemSourcePolicy.Kind.CONTACTS -> addressBooks(control) }
            }
        }
    }
    private fun Cursor.text(column: String): String? = getColumnIndexOrThrow(column).let { if(isNull(it)) null else getString(it) }
    private fun calendars(control: Control): List<SystemSourcePolicy.Source> {
        val columns=arrayOf(Calendars._ID,Calendars.CALENDAR_DISPLAY_NAME,Calendars.ACCOUNT_NAME,Calendars.ACCOUNT_TYPE,Calendars.CALENDAR_ACCESS_LEVEL)
        val result=ArrayList<SystemSourcePolicy.Source>()
        val cursor=context.contentResolver.query(Calendars.CONTENT_URI,columns,null,null,Calendars._ID+" ASC",control.signal)
            ?: error("provider_unavailable")
        cursor.use { while(it.moveToNext()) {
            control.check(); check(result.size<1000) { "source_limit" }
            val id=it.text(Calendars._ID) ?: error("provider_unavailable")
            val account=it.text(Calendars.ACCOUNT_NAME)
            result.add(SystemSourcePolicy.Source(SystemSourcePolicy.uid(SystemSourcePolicy.Kind.EVENTS,
                "calendar",it.text(Calendars.ACCOUNT_TYPE),account,id),SystemSourcePolicy.label(it.text(Calendars.CALENDAR_DISPLAY_NAME),account),
                SystemSourcePolicy.Kind.EVENTS,(it.text(Calendars.CALENDAR_ACCESS_LEVEL)?.toIntOrNull() ?: 0)>=Calendars.CAL_ACCESS_CONTRIBUTOR))
        } }
        return result
    }
    private fun addressBooks(control: Control): List<SystemSourcePolicy.Source> {
        // RawContacts exposes actual provider-backed source tuples, including local contacts.
        // Only account metadata is projected; no contact names, phone numbers, or bodies are read.
        val result=LinkedHashMap<String,SystemSourcePolicy.Source>()
        var rows=0
        fun collect(cursor: Cursor, accountName: String, accountType: String, dataSet: String) {
            cursor.use { while(it.moveToNext()) {
                control.check(); check(++rows<=20_000) { "source_limit" }
                val name=it.text(accountName);val type=it.text(accountType);val dataset=it.text(dataSet)
                val uid=SystemSourcePolicy.uid(SystemSourcePolicy.Kind.CONTACTS,"contacts",type,name,dataset)
                result[uid]=SystemSourcePolicy.Source(uid,SystemSourcePolicy.label(name,type),SystemSourcePolicy.Kind.CONTACTS)
                check(result.size<=1000) { "source_limit" }
            } }
        }
        // Configured empty address books can appear in Settings even before a raw contact exists.
        collect(context.contentResolver.query(Settings.CONTENT_URI,arrayOf(Settings.ACCOUNT_NAME,Settings.ACCOUNT_TYPE,Settings.DATA_SET),
            null,null,null,control.signal) ?: error("provider_unavailable"),Settings.ACCOUNT_NAME,Settings.ACCOUNT_TYPE,Settings.DATA_SET)
        collect(context.contentResolver.query(RawContacts.CONTENT_URI,arrayOf(RawContacts.ACCOUNT_NAME,RawContacts.ACCOUNT_TYPE,RawContacts.DATA_SET),
            RawContacts.DELETED+"=0",null,null,control.signal) ?: error("provider_unavailable"),RawContacts.ACCOUNT_NAME,RawContacts.ACCOUNT_TYPE,RawContacts.DATA_SET)
        return result.values.toList()
    }
}
