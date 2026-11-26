package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/** A read request is never a provider-write, synchronization or deletion grant. Refs #791. */
internal data class SystemImportRequest(
    val kind: SystemSourcePolicy.Kind, val sourceUid: String, val requestId: String,
    val session: String, val revision: String, val from: Long? = null, val to: Long? = null,
    val dateFrom: String? = null, val dateTo: String? = null
) {
    companion object {
        const val COMMAND = "android_systemimport"
        const val CALLBACK = "androidSystemImport"
        const val MAX_WINDOW = 366L * 86_400_000L
        fun parse(value: JSONObject): SystemImportRequest {
            require(value.opt("cmd") == COMMAND) { "invalid_request" }
            fun text(key: String): String = (value.opt(key) as? String)?.also {
                require(it.isNotEmpty() && it.toByteArray(Charsets.UTF_8).size <= 1024) { "invalid_request" }
            } ?: error("invalid_request")
            val kind = SystemSourcePolicy.kind(text("art"))
            val allowed = setOf("cmd", "art", "sourceUid", "requestId", "session", "revision") +
                if (kind == SystemSourcePolicy.Kind.EVENTS) setOf("from", "to", "dateFrom", "dateTo") else emptySet()
            require(value.keys().asSequence().toSet() == allowed) { "invalid_request" }
            val source = text("sourceUid")
            require(source.matches(Regex("android-${kind.wire}:[0-9a-f]{64}"))) { "invalid_request" }
            fun instant(key: String): Long {
                val input = value.opt(key)
                require(input is Int || input is Long) { "invalid_request" }
                return (input as Number).toLong().also {
                    require(it in -62_135_596_800_000L..253_402_300_799_999L) { "invalid_request" }
                }
            }
            val from = if (kind == SystemSourcePolicy.Kind.EVENTS) instant("from") else null
            val to = if (kind == SystemSourcePolicy.Kind.EVENTS) instant("to") else null
            val dateFrom = if (kind == SystemSourcePolicy.Kind.EVENTS) text("dateFrom") else null
            val dateTo = if (kind == SystemSourcePolicy.Kind.EVENTS) text("dateTo") else null
            return SystemImportRequest(kind, source, text("requestId"), text("session"), text("revision"), from, to, dateFrom, dateTo)
                .also { if (kind == SystemSourcePolicy.Kind.EVENTS) SystemImportWindow.of(it) }
        }
    }
    fun reply(): JSONObject = JSONObject().put("requestId", requestId).put("kind", kind.wire)
        .put("sourceUid", sourceUid).put("session", session).put("revision", revision)
        .also { if (from != null) it.put("from", from).put("to", to).put("dateFrom", dateFrom).put("dateTo", dateTo) }
    fun failure(code: String): JSONObject = reply().put("ok", false).put("errorCode", code)
}

/** Android all-day values encode calendar dates at UTC midnight, not local instants. */
internal data class SystemImportWindow(val from: Long, val to: Long, val dayFrom: Long, val dayTo: Long) {
    val queryFrom: Long get() = minOf(from, dayFrom)
    val queryTo: Long get() = maxOf(to, dayTo)
    fun contains(begin: Long, end: Long, allDay: Boolean): Boolean {
        require(end >= begin) { "provider_unavailable" }
        if (allDay) {
            require(begin % DAY == 0L && end % DAY == 0L && end > begin) { "provider_unavailable" }
            return begin < dayTo && end > dayFrom
        }
        return begin < to && (end > from || begin == end && begin >= from)
    }
    companion object {
        const val DAY = 86_400_000L
        fun of(request: SystemImportRequest): SystemImportWindow {
            require(request.kind == SystemSourcePolicy.Kind.EVENTS) { "invalid_request" }
            fun day(text: String?): LocalDate {
                require(text != null && text.matches(Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}"))) { "invalid_request" }
                return try { LocalDate.parse(text).also { require(it.year in 1..9999) } }
                    catch (_: Exception) { throw IllegalArgumentException("invalid_request") }
            }
            val first = day(request.dateFrom); val last = day(request.dateTo)
            val count = last.toEpochDay() - first.toEpochDay() + 1
            require(count in 1..366) { "invalid_request" }
            val dayFrom = first.atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli()
            val dayTo = last.plusDays(1).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli()
            val from = requireNotNull(request.from); val to = requireNotNull(request.to)
            require(to > from && to - from <= SystemImportRequest.MAX_WINDOW + 2 * DAY) { "invalid_request" }
            // The web core supplies the selected zone's instants. Bound their relationship to
            // the explicit dates without guessing that zone from the device or its UTC offset.
            require(from in dayFrom - DAY..dayFrom + DAY && to in dayTo - DAY..dayTo + DAY) { "invalid_request" }
            return SystemImportWindow(from, to, dayFrom, dayTo)
        }
    }
}

/** Pure, bounded projections; provider-only and unsupported metadata grants no authority. */
internal object SystemImportPolicy {
    const val MAX_RECORDS = 5000
    const val MAX_ROWS = 50_000
    const val MAX_BYTES = 4 * 1024 * 1024
    const val MAX_TEXT_BYTES = 65_536
    const val NAME = "vnd.android.cursor.item/name"
    const val PHONE = "vnd.android.cursor.item/phone_v2"
    const val EMAIL = "vnd.android.cursor.item/email_v2"
    const val POSTAL = "vnd.android.cursor.item/postal-address_v2"
    const val ORGANIZATION = "vnd.android.cursor.item/organization"
    const val NOTE = "vnd.android.cursor.item/note"
    const val EVENT = "vnd.android.cursor.item/contact_event"
    val contactMimeTypes = listOf(NAME, PHONE, EMAIL, POSTAL, ORGANIZATION, NOTE, EVENT)
    data class Detail(val mime: String, val fields: List<String?>) {
        fun value(column: Int): String = fields.getOrNull(column - 1).orEmpty().also {
            require(it.toByteArray(Charsets.UTF_8).size <= MAX_TEXT_BYTES) { "record_limit" }
        }
    }
    data class CalendarInstance(val eventId: String, val begin: Long, val end: Long,
        val allDay: Boolean, val title: String, val description: String, val location: String)

    class Batch(private val request: SystemImportRequest) {
        private val records = JSONArray()
        private val ids = HashSet<String>()
        private var bytes = request.reply().toString().toByteArray(Charsets.UTF_8).size + 256
        fun add(id: String, data: JSONObject) {
            require(records.length() < MAX_RECORDS) { "record_limit" }
            require(ids.add(id)) { "provider_changed" }
            require(data.optString("uid") == id) { "provider_unavailable" }
            val record = JSONObject().put("recordId", id).put("data", data)
            bytes += record.toString().toByteArray(Charsets.UTF_8).size + 1
            require(bytes <= MAX_BYTES) { "record_limit" }
            records.put(record)
        }
        fun result(): JSONObject = request.reply().put("ok", true).put("complete", true)
            .put("scope", if (request.kind == SystemSourcePolicy.Kind.CONTACTS) "source-contacts" else "calendar-instances-window")
            .put("records", records)
    }

    fun recordId(kind: SystemSourcePolicy.Kind, source: String, vararg identity: String): String =
        "android-${if (kind == SystemSourcePolicy.Kind.CONTACTS) "contact" else "event"}:" +
            SystemSourcePolicy.uid(kind, source, *identity).substringAfter(':')

    private fun types(type: Int?, phone: Boolean = false, email: Boolean = false): List<String> = when (type) {
        1 -> listOf("HOME")
        2 -> if (phone) listOf("CELL") else listOf("WORK")
        3 -> if (phone) listOf("WORK") else emptyList()
        4 -> if (phone) listOf("WORK", "FAX") else if (email) listOf("CELL") else emptyList()
        5 -> if (phone) listOf("HOME", "FAX") else emptyList()
        6 -> if (phone) listOf("PAGER") else emptyList()
        17 -> if (phone) listOf("WORK", "CELL") else emptyList()
        18 -> if (phone) listOf("WORK", "PAGER") else emptyList()
        19 -> if (phone) listOf("ASSISTANT") else emptyList()
        else -> emptyList()
    }
    private fun label(row: Detail, phone: Boolean = false, email: Boolean = false): JSONObject = JSONObject()
        .put("typen", JSONArray(types(row.value(2).toIntOrNull(), phone, email)))
        .also { if (row.value(2) == "0" && row.value(3).isNotEmpty()) it.put("label", row.value(3)) }

    fun contact(source: String, rawId: String, displayName: String, details: List<Detail>): JSONObject {
        require(rawId.matches(Regex("[0-9]+"))) { "provider_unavailable" }
        require(details.size <= MAX_ROWS && displayName.toByteArray().size <= MAX_TEXT_BYTES) { "record_limit" }
        val result = JSONObject().put("uid", recordId(SystemSourcePolicy.Kind.CONTACTS, source, rawId))
            .put("anzeigename", displayName).put("sync", false)
        val phones = JSONArray(); val emails = JSONArray(); val addresses = JSONArray()
        val notes = ArrayList<String>(); val organizations = ArrayList<String>()
        val unsupportedDates = JSONArray()
        for (row in details) {
            require(row.mime in contactMimeTypes) { "provider_unavailable" }
            // Validate every requested field, including fields retained only as provider metadata.
            for (i in 1..row.fields.size) row.value(i)
            when (row.mime) {
                NAME -> {
                    if (!result.has("vorname")) {
                        result.put("vorname", row.value(2)).put("nachname", row.value(3))
                        if (row.value(1).isNotBlank()) result.put("anzeigename", row.value(1))
                    }
                }
                PHONE -> if (row.value(1).isNotBlank()) phones.put(label(row, phone = true).put("wert", row.value(1)))
                EMAIL -> if (row.value(1).isNotBlank()) emails.put(label(row, email = true).put("wert", row.value(1)))
                POSTAL -> addresses.put(label(row).put("strasse", row.value(4).ifBlank { row.value(1) })
                    .put("postfach", row.value(5)).put("zusatz", row.value(6)).put("ort", row.value(7))
                    .put("region", row.value(8)).put("plz", row.value(9)).put("land", row.value(10)))
                ORGANIZATION -> if (row.value(1).isNotBlank()) organizations.add(row.value(1))
                NOTE -> if (row.value(1).isNotBlank()) notes.add(row.value(1))
                EVENT -> {
                    val field = when (row.value(2)) { "3" -> "geburtstag"; "1" -> "jubilaeum"; else -> null }
                    val date = date(row.value(1))
                    if (field != null && date != null && !result.has(field)) result.put(field, date)
                    else unsupportedDates.put(JSONObject().put("value", row.value(1)).put("type", row.value(2)).put("label", row.value(3)))
                }
            }
        }
        if (!result.has("vorname")) result.put("vorname", "").put("nachname", "")
        result.put("firma", organizations.distinct().joinToString("\n"))
            .put("notiz", notes.distinct().joinToString("\n\n"))
            .put("telefone", phones).put("emailEintraege", emails).put("anschriften", addresses)
        if (result.optString("vorname").isBlank() && result.optString("nachname").isBlank() && result.optString("firma").isBlank())
            result.put("nachname", result.optString("anzeigename"))
        if (unsupportedDates.length() > 0) result.put("androidContactDates", unsupportedDates)
        return result
    }

    private fun date(raw: String): String? = try {
        val text = if (raw.matches(Regex("[0-9]{8}"))) "${raw.substring(0, 4)}-${raw.substring(4, 6)}-${raw.substring(6)}" else raw
        if (text.matches(Regex("--[0-9]{2}-[0-9]{2}"))) { LocalDate.parse("2000" + text.substring(1)); text }
        else if (text.matches(Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}"))) { require(LocalDate.parse(text).year in 1..9999); text }
        else null
    } catch (_: Exception) { null }

    fun calendar(source: String, instance: CalendarInstance): JSONObject {
        require(instance.eventId.matches(Regex("[0-9]+")) && instance.end >= instance.begin) { "provider_unavailable" }
        for (text in listOf(instance.title, instance.description, instance.location))
            require(text.toByteArray(Charsets.UTF_8).size <= MAX_TEXT_BYTES) { "record_limit" }
        val start = Instant.ofEpochMilli(instance.begin).atOffset(ZoneOffset.UTC)
        val end = Instant.ofEpochMilli(instance.end).atOffset(ZoneOffset.UTC)
        require(start.year in 1..9999 && end.year in 1..9999) { "provider_unavailable" }
        val id = recordId(SystemSourcePolicy.Kind.EVENTS, source, instance.eventId, instance.begin.toString())
        val result = JSONObject().put("uid", id).put("titel", instance.title).put("notiz", instance.description)
            .put("ort", instance.location).put("sync", false).put("standardErinnerung", false)
            .put("wiederholung", JSONObject().put("art", "none").put("bis", ""))
            .put("icsAnzeigeZeitzone", "UTC").put("icsEndeFehlt", false)
            .put("icsNullDauer", instance.begin == instance.end)
        val lines = JSONArray()
        if (instance.allDay) {
            require(instance.begin % 86_400_000 == 0L && instance.end % 86_400_000 == 0L && instance.end > instance.begin) { "provider_unavailable" }
            val last = end.toLocalDate().minusDays(1)
            result.put("datum", start.toLocalDate().toString()).put("zeit", "")
                .put("endDatum", if (last == start.toLocalDate()) "" else last.toString()).put("endZeit", "")
            lines.put("DTSTART;VALUE=DATE:" + start.toLocalDate().format(DateTimeFormatter.BASIC_ISO_DATE))
                .put("DTEND;VALUE=DATE:" + end.toLocalDate().format(DateTimeFormatter.BASIC_ISO_DATE))
        } else {
            // UTC fields plus UTC roundtrip preserve the exact instant across Android TZDB changes.
            fun clock(value: java.time.OffsetDateTime): String = value.format(DateTimeFormatter.ofPattern(if (value.second == 0) "HH:mm" else "HH:mm:ss"))
            require(instance.begin % 1000 == 0L && instance.end % 1000 == 0L) { "provider_unavailable" }
            result.put("datum", start.toLocalDate().toString()).put("zeit", clock(start))
                .put("endDatum", if (end.toLocalDate() == start.toLocalDate()) "" else end.toLocalDate().toString()).put("endZeit", clock(end))
            val format = DateTimeFormatter.ofPattern("uuuuMMdd'T'HHmmss'Z'")
            lines.put("DTSTART:" + start.format(format)).put("DTEND:" + end.format(format))
        }
        return result.put("icsRoundtrip", lines)
    }
}
