package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject

/** Canonical ICS actions select a whole collection. No frontend record body or filter is trusted. */
internal class CalendarExportRequest private constructor(val kind: ICalendarExport.Kind, val requestId: String) {
    val collection: String get() = when (kind) {
        ICalendarExport.Kind.appointments -> "termine"
        ICalendarExport.Kind.tasks -> "aufgaben"
        ICalendarExport.Kind.anniversaries -> "jahrestage"
    }
    val fileName get() = "Magnolie-$collection.ics"
    fun records(book: JSONObject): List<JSONObject> {
        val array = book.getJSONArray(collection)
        require(array.length() in 1..ICalendarExport.maximumRecords)
        return (0 until array.length()).map { array.get(it) as? JSONObject ?: error("Invalid calendar record") }
    }
    companion object {
        fun write(output: java.io.OutputStream?, text: String) {
            requireNotNull(output) { "No document output stream" }.use {
                it.write(text.toByteArray(Charsets.UTF_8)); it.flush()
            }
        }
        fun parse(message: JSONObject): CalendarExportRequest {
            require(message.keys().asSequence().toSet() == setOf("cmd","art","requestId","session","revision"))
            require(message.opt("cmd") == "tablet_export_ics")
            for (field in listOf("session","revision","requestId")) {
                val value = message.opt(field) as? String ?: error("Invalid export authority")
                require(value.isNotEmpty() && value.toByteArray().size <= 1024)
            }
            val kind = ICalendarExport.Kind.entries.firstOrNull { it.wire == message.opt("art") } ?: error("Unsupported calendar export")
            return CalendarExportRequest(kind,message.getString("requestId"))
        }
    }
}
