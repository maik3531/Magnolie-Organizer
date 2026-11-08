package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.concurrent.CancellationException

/** Bounded, source-preserving RFC 5545 export. Records are never expanded into
 * occurrences and an unsupported or contradictory item rejects the whole file. */
object ICalendarExport {
    const val maximumBytes = 32 * 1024 * 1024
    const val maximumRecords = 50_000
    enum class Kind(val wire: String) { appointments("ics-termine"), tasks("ics-aufgaben"), anniversaries("ics-jahrestage") }
    class ExportException(message: String) : IllegalArgumentException(message)
    private fun requireExport(ok: Boolean, message: String = "Calendar data cannot be exported without loss. Use a complete JSON backup; nothing was exported.") { if (!ok) throw ExportException(message) }
    private fun matches(text: String, pattern: String) = Regex(pattern).matches(text)
    private fun upper(value: String) = value.uppercase(Locale.ROOT)
    private fun text(record: JSONObject, name: String) = record.opt(name) as? String ?: ""
    private fun meaningful(value: Any?): Boolean = when (value) {
        null, JSONObject.NULL -> false
        is String -> value.isNotEmpty()
        is Boolean -> value
        is Number -> value.toDouble() != 0.0
        is JSONArray -> value.length() > 0
        is JSONObject -> value.keys().asSequence().any { meaningful(value.opt(it)) }
        else -> true
    }
    private fun integer(value: Any?, fallback: Long): Long {
        if (value == null) return fallback
        requireExport(value is Number, "Invalid integer calendar field.")
        val n = (value as Number).toDouble()
        requireExport(n.isFinite() && n == kotlin.math.round(n) && kotlin.math.abs(n) <= 9_007_199_254_740_991.0, "Invalid integer calendar field.")
        return value.toLong()
    }
    private fun escape(value: String) = value.replace("\\", "\\\\").replace("\r\n", "\n").replace('\r', '\n').replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
    private fun unescape(value: String): String = buildString {
        var escaped = false
        for (c in value) {
            if (escaped) { append(if (c == 'n' || c == 'N') '\n' else c); escaped = false }
            else if (c == '\\') escaped = true else append(c)
        }
        if (escaped) append('\\')
    }
    private fun hash(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it.toInt() and 255) }
    private fun strings(value: Any?): List<String> {
        requireExport(value is JSONArray, "Invalid calendar string array.")
        return (0 until (value as JSONArray).length()).map { index ->
            val line = value.get(index); requireExport(line is String, "Invalid calendar string array."); line as String
        }
    }
    private class Property(val line: String) {
        val name: String; val value: String; val header: String
        val parameters = linkedMapOf<String, String>()
        init {
            requireExport(line.isNotEmpty() && line.none { it == '\r' || it == '\n' || it == '\u0000' || it.code < 32 && it != '\t' }, "Invalid calendar content line.")
            requireExport(line.toByteArray(Charsets.UTF_8).size <= 1024 * 1024, "Calendar content line is too large.")
            var quoted = false; var at = -1
            for (i in line.indices) { if (line[i] == '"') quoted = !quoted else if (line[i] == ':' && !quoted) { at = i; break } }
            requireExport(at >= 0 && !quoted, "Invalid calendar property header.")
            header = line.substring(0, at); value = line.substring(at + 1)
            val fields = mutableListOf<String>(); val field = StringBuilder(); quoted = false
            for (c in header) {
                if (c == '"') quoted = !quoted
                if (c == ';' && !quoted) { fields.add(field.toString()); field.setLength(0) } else field.append(c)
            }
            fields.add(field.toString()); requireExport(matches(fields.first(), "[A-Za-z0-9-]+"), "Invalid calendar property name.")
            name = upper(fields.first())
            for (part in fields.drop(1)) {
                val pair = part.split('=', limit = 2)
                requireExport(pair.size == 2 && matches(pair[0], "[A-Za-z0-9-]+") && !parameters.containsKey(upper(pair[0])), "Invalid calendar parameter.")
                var value = pair[1]
                if (value.startsWith('"')) { requireExport(value.length >= 2 && value.endsWith('"'), "Invalid quoted calendar parameter."); value = value.substring(1, value.lastIndex) }
                parameters[upper(pair[0])] = value
            }
        }
    }
    private val utc: ZoneId = ZoneOffset.UTC
    private val stamp = DateTimeFormatter.ofPattern("uuuuMMdd'T'HHmmss", Locale.ROOT)
    private val days = listOf("SU", "MO", "TU", "WE", "TH", "FR", "SA")
    private fun day(value: String): LocalDate {
        requireExport(matches(value, "[0-9]{4}-[0-9]{2}-[0-9]{2}"), "Invalid calendar date.")
        return try { LocalDate.parse(value).also { requireExport(it.year in 1..9999, "Invalid calendar year.") } } catch (_: java.time.DateTimeException) { throw ExportException("Invalid calendar date.") }
    }
    private fun zone(value: String): ZoneId {
        requireExport(value.isNotEmpty() && value.length <= 255 && matches(value, "[A-Za-z0-9_+./-]+") && !value.contains(".."), "Unavailable calendar time zone.")
        return try { ZoneId.of(value) } catch (_: java.time.DateTimeException) { throw ExportException("Unavailable calendar time zone.") }
    }
    private fun displayZone(record: JSONObject) = text(record, "icsAnzeigeZeitzone").let { if (it.isEmpty() || it == "system") ZoneId.systemDefault() else zone(it) }
    private fun wall(date: String, time: String): LocalDateTime {
        val day = day(date)
        requireExport(matches(time, "(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?"), "Invalid calendar clock.")
        return day.atTime(time.substring(0, 2).toInt(), time.substring(3, 5).toInt(), if (time.length == 8) time.substring(6, 8).toInt() else 0)
    }
    private fun ordinaryWall(value: LocalDateTime, zone: ZoneId): Long {
        val offsets = zone.rules.getValidOffsets(value)
        requireExport(offsets.isNotEmpty(), "A calendar wall time falls in a daylight-saving gap; export was cancelled.")
        return offsets.minOf { value.toEpochSecond(it) }
    }
    private fun timeLine(name: String, date: String, time: String, zoneName: String): String {
        day(date)
        if (time.isEmpty()) return "$name;VALUE=DATE:" + date.replace("-", "")
        val resolved = if (zoneName.isEmpty() || zoneName == "system") ZoneId.systemDefault() else zone(zoneName)
        val local = wall(date, time); ordinaryWall(local, resolved)
        return name + (if (zoneName.isEmpty() || zoneName == "system" || zoneName == "UTC") "" else ";TZID=$zoneName") + ":" + local.format(stamp) + (if (zoneName == "UTC") "Z" else "")
    }
    private data class Clock(val instant: Long, val wall: LocalDateTime, val dateOnly: Boolean, val source: String, val floating: Boolean)
    private class Resolver(val definitions: Map<String, List<String>>, val check: () -> Unit) {
        private val resolved = linkedMapOf<String, Long>()
        fun instant(wall: LocalDateTime, source: String, default: ZoneId): Long {
            if (source == "@utc") return wall.toEpochSecond(ZoneOffset.UTC)
            if (source.isEmpty()) return ordinaryWall(wall, default)
            if (!definitions.containsKey(source)) return ordinaryWall(wall, zone(source))
            val key = source + "\u0000" + wall.toString()
            return resolved[key] ?: run {
                // Reuse the existing public, bounded, calendar-scoped resolver.
                // DTSTAMP preserves exact epoch seconds, including custom offsets
                // beyond java.time.ZoneOffset's 18-hour limit. No event expansion.
                val parameter = if (source.any { it == ':' || it == ';' || it == ',' }) "\"$source\"" else source
                val lines = listOf("BEGIN:VCALENDAR", "VERSION:2.0") + definitions.getValue(source) + listOf(
                    "BEGIN:VEVENT", "UID:timezone-probe", "DTSTART:20000101T000000Z", "DTSTAMP;TZID=$parameter:" + wall.format(stamp), "SUMMARY:Timezone resolution", "END:VEVENT", "END:VCALENDAR")
                val bytes = lines.joinToString("\r\n", postfix = "\r\n").toByteArray(Charsets.UTF_8)
                val result = ICalendarImport.decode(bytes, "UTC", checkCancelled = check).appointments.single().getLong("geaendert") / 1000
                if (resolved.size >= 1024) resolved.clear()
                resolved[key] = result; result
            }
        }
        fun clock(property: Property, default: ZoneId): Clock {
            val value = property.value
            val allDay = upper(property.parameters["VALUE"] ?: "") == "DATE" || matches(value, "[0-9]{8}")
            requireExport(property.parameters.keys.all { it in setOf("TZID", "VALUE", "RANGE") } && (property.parameters["RANGE"] == null || property.name == "RECURRENCE-ID" && upper(property.parameters.getValue("RANGE")) == "THISANDFUTURE"), "Unsupported calendar time parameters.")
            if (allDay) {
                requireExport(matches(value, "[0-9]{8}") && property.parameters["TZID"] == null, "Invalid date-only calendar property.")
                val date = day(value.substring(0, 4) + "-" + value.substring(4, 6) + "-" + value.substring(6, 8)).atStartOfDay()
                return Clock(date.toEpochSecond(ZoneOffset.UTC), date, true, "@utc", true)
            }
            requireExport(matches(value, "[0-9]{8}T[0-9]{6}Z?") && property.parameters["VALUE"]?.let { upper(it) == "DATE-TIME" } != false && (!value.endsWith('Z') || property.parameters["TZID"] == null), "Invalid calendar date-time.")
            val source = if (value.endsWith('Z')) "@utc" else property.parameters["TZID"] ?: ""
            val local = wall(value.substring(0, 4) + "-" + value.substring(4, 6) + "-" + value.substring(6, 8), value.substring(9, 11) + ":" + value.substring(11, 13) + ":" + value.substring(13, 15))
            return Clock(instant(local, source, default), local, false, source, !value.endsWith('Z') && property.parameters["TZID"] == null)
        }
        fun duration(value: String, start: Clock, default: ZoneId): Clock {
            val match = Regex("\\+?P(?:(\\d+)W|(?:(\\d+)D)?(?:T(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+)S)?)?)").matchEntire(value) ?: throw ExportException("Invalid calendar duration.")
            val values = (1..5).map { index -> match.groups[index]?.value?.let {
                it.toLongOrNull() ?: throw ExportException("Calendar duration exceeds the supported range.")
            } ?: 0L }
            requireExport((1..5).any { match.groups[it] != null } && values.all { it in 0..1_000_000 } && (!start.dateOnly || values.drop(2).all { it == 0L }), "Invalid or excessive calendar duration.")
            val wall = start.wall.plusDays(values[0] * 7 + values[1]); val seconds = values[2] * 3600 + values[3] * 60 + values[4]
            return Clock(instant(wall, start.source, default) + seconds, wall.plusSeconds(seconds), start.dateOnly, start.source, start.floating)
        }
    }
    private val metadata = setOf("id", "uid", "angelegt", "geaendert", "angelegtGeschaetzt", "ursprungApp", "personalGeaendert", "personalVersion", "kalenderQuelle", "syncKalenderUid", "icsQuelleId", "icsQuelleName", "icsImportUid", "icsSerienUid", "icsAnzeigeZeitzone", "icsKomplex", "icsAenderungszeitFehlt", "icsSequence", "icsStatus", "icsTimezones", "icsRoundtrip", "baumFreigabe", "baumGeaendert", "baumInhaltVersion", "baumVersion", "baumQuelle", "persoenlichVerknuepft", "geloescht")
    private fun validateRecord(record: JSONObject, kind: Kind) {
        val allowed = metadata + setOf("notiz", "kategorien", "akzentFarbe") + when (kind) {
            Kind.appointments -> setOf("titel", "datum", "zeit", "endDatum", "endZeit", "ganztag", "ort", "wiederholung", "icsAusnahmen", "icsZusatzDaten", "icsZusatzTermine", "icsRangeOverrides", "icsEndeFehlt", "icsNullDauer", "vertraulich", "vorlaeufig", "kostenstelle", "kunde", "individuelleErinnerungTage", "standardErinnerung", "alarme")
            Kind.tasks -> setOf("titel", "startDatum", "startZeit", "faellig", "faelligZeit", "prio", "erledigt", "erinnern", "individuelleErinnerungTage", "elternUid", "icsElternUid", "icsElternQuelleId", "reihenfolge", "personen", "wiederholung", "erinnerungsMinute")
            Kind.anniversaries -> setOf("name", "datum", "typ", "kontaktId", "quelle")
        }
        for (key in listOf("ganztag", "icsEndeFehlt", "icsNullDauer", "vertraulich", "vorlaeufig", "erledigt", "erinnern", "standardErinnerung")) if (record.has(key)) requireExport(record.get(key) is Boolean, "Invalid boolean calendar field.")
        for (key in record.keys()) requireExport(key in allowed || !meaningful(record.get(key)))
        // These known local-only fields have no ICS representation. Do not
        // silently accept meaningful values merely because they are known.
        if (kind == Kind.tasks) requireExport(!meaningful(record.opt("personen")), "Task person assignments require a full JSON backup.")
    }
    private fun validateSourceDisplay(record: JSONObject) {
        val value = record.opt("kalenderQuelle") ?: return
        if (value === JSONObject.NULL) return
        requireExport(value is JSONObject, "Invalid calendar source display metadata.")
        val source = value as JSONObject
        val limits = mapOf("id" to 200, "name" to 200, "gruppe" to 200, "farbe" to 7, "anbieter" to 100)
        for (key in source.keys()) {
            val text = source.opt(key)
            requireExport(key in limits && text is String && text.length <= limits.getValue(key) &&
                text.none { it < ' ' && it !in "\t\n\r" || it == '\u007f' }, "Invalid calendar source display metadata.")
        }
        val color = text(source,"farbe")
        requireExport(color.isEmpty() || matches(color,"#[0-9a-fA-F]{6}"), "Invalid calendar source color.")
        val actual = text(source,"id")
        val expected = text(record,"icsQuelleId").ifEmpty { text(record,"syncKalenderUid") }
            .filterNot { it < ' ' && it !in "\t\n\r" || it == '\u007f' }.take(200).trim()
        requireExport(expected.isEmpty() || actual.isEmpty() || actual == expected, "Calendar display source contradicts its stored source identity.")
    }
    private fun validateAlarms(record: JSONObject, properties: List<Property>) {
        if (!record.has("alarme")) return // Raw-only source records retain their whole original alarm blocks.
        val value = record.opt("alarme")
        requireExport(value is JSONArray, "Invalid structured calendar alarms.")
        val alarms = value as JSONArray
        requireExport(alarms.length() <= 32, "Too many structured calendar alarms.")
        val expected = linkedMapOf<String, Map<String, Any>>()
        var block: MutableList<Property>? = null
        for (property in properties) {
            if (property.name == "BEGIN") { block = mutableListOf(); continue }
            if (property.name != "END") { block?.add(property); continue }
            val parts = block ?: continue
            block = null
            val triggers = parts.filter { it.name == "TRIGGER" }; val actions = parts.filter { it.name == "ACTION" }
            requireExport(triggers.size == 1 && actions.size == 1, "Calendar alarms require unambiguous source triggers and actions.")
            val trigger = triggers.single(); val raw = trigger.value.trim()
            val action = actions.single().value.trim().lowercase(Locale.ROOT)
            val related = upper(trigger.parameters["RELATED"] ?: "START")
            requireExport(related in setOf("START","END") && raw.isNotEmpty() && raw.length <= 500 && action.length <= 40,
                "Unsupported calendar alarm projection.")
            val tzid = (trigger.parameters["TZID"] ?: "").trim()
            requireExport(tzid.length <= 200, "Unsupported calendar alarm time zone.")
            val match = Regex("-P(?:(\\d+)W)?(?:(\\d+)D)?(?:T(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+)S)?)?",RegexOption.IGNORE_CASE).matchEntire(raw)
            val groups = match?.groupValues?.drop(1)
            val numbers = groups?.map { if (it.isEmpty()) 0.0 else it.toDoubleOrNull() ?: Double.POSITIVE_INFINITY }
            val minutes = numbers?.let { it[0]*10080 + it[1]*1440 + it[2]*60 + it[3] + kotlin.math.ceil(it[4]/60) }
            val relative = groups?.any(String::isNotEmpty) == true && minutes != null && minutes.isFinite() && minutes >= 0 && minutes <= 525600 && minutes == kotlin.math.floor(minutes)
            val editable = relative && action == "display"
            val offset = if (editable) minutes!!.toLong() else 0L
            val key = if (editable) "$offset|$related|$action" else "raw|$raw|$related"
            expected.putIfAbsent(key,mapOf("offsetMinuten" to offset, "aktion" to action, "related" to related,
                "triggerRaw" to raw,"triggerTzid" to tzid,"bearbeitbar" to editable))
        }
        val seen = mutableSetOf<String>()
        val allowed = setOf("id","offsetMinuten","aktion","aktiviert","quelle","related","triggerRaw","triggerTzid","bearbeitbar")
        for (index in 0 until alarms.length()) {
            val alarm = alarms.opt(index) as? JSONObject ?: throw ExportException("Invalid structured calendar alarm.")
            requireExport(alarm.keys().asSequence().all { it in allowed }, "Unsupported structured alarm field.")
            for (key in listOf("aktion","related","triggerRaw","triggerTzid")) if (alarm.has(key))
                requireExport(alarm.opt(key) is String, "Invalid structured alarm field type.")
            requireExport(alarm.opt("id") is String && matches(text(alarm,"id"),"[A-Za-z0-9_.:@-]{1,160}") &&
                alarm.opt("aktiviert") is Boolean && alarm.opt("bearbeitbar") is Boolean && text(alarm,"quelle") in setOf("ics","magnolie"),
                "Edited or disabled alarms require matching source VALARM data.")
            val offset = integer(alarm.opt("offsetMinuten"),-1)
            val editable = alarm.getBoolean("bearbeitbar"); val raw = text(alarm,"triggerRaw")
            val related = text(alarm,"related"); val action = text(alarm,"aktion")
            val key = if (editable) "$offset|$related|$action" else "raw|$raw|$related"
            if (!alarm.getBoolean("aktiviert")) {
                // Disabled editable alarms may remain as local JSON metadata only
                // after their corresponding authoritative VALARM has been removed.
                requireExport(editable && action == "display" && related in setOf("START","END") && offset in 0..525600 &&
                    key !in expected && seen.add(key), "Disabled alarms still have source VALARM data or are not editable.")
                continue
            }
            val source = expected[key] ?: throw ExportException("Structured alarm contradicts its source VALARM.")
            requireExport(seen.add(key) && offset == source["offsetMinuten"] && action == source["aktion"] &&
                related == source["related"] && (editable || raw == source["triggerRaw"]) && (editable || text(alarm,"triggerTzid") == source["triggerTzid"]) &&
                editable == source["bearbeitbar"], "Structured alarm contradicts its source VALARM.")
        }
        requireExport(expected.keys.all { it in seen }, "Structured alarms omit an existing source VALARM.")
    }
    private fun identifier(record: JSONObject): String = listOf("icsSerienUid", "icsImportUid", "uid", "id").firstNotNullOfOrNull { text(record, it).takeIf(String::isNotEmpty) }
        ?: throw ExportException("Calendar record has no stable identity.")
    private fun raw(record: JSONObject): List<Property> {
        val lines = record.opt("icsRoundtrip")?.let(::strings) ?: emptyList()
        var depth = 0; val singles = mutableSetOf<String>()
        val unique = setOf("UID", "DTSTART", "DTEND", "DUE", "DURATION", "RRULE", "EXRULE", "RECURRENCE-ID", "SUMMARY", "DESCRIPTION", "STATUS", "CLASS", "SEQUENCE", "PRIORITY", "PERCENT-COMPLETE")
        val result = lines.map { line ->
            var property = Property(line)
            if (property.parameters["TZID"] == "" && property.name in setOf("DTSTART", "DTEND", "DUE", "RECURRENCE-ID", "EXDATE", "RDATE")) property = Property(line.replace(Regex(";TZID=(?:\"\")?(?=;|:)", RegexOption.IGNORE_CASE), ""))
            when (property.name) {
                "BEGIN" -> { requireExport(depth == 0 && upper(property.value) == "VALARM", "Invalid nested calendar component."); depth = 1 }
                "END" -> { requireExport(depth == 1 && upper(property.value) == "VALARM", "Unbalanced calendar alarm."); depth = 0 }
                else -> if (depth == 0 && property.name in unique) requireExport(singles.add(property.name), "Duplicate source calendar property.")
            }
            property
        }
        requireExport(depth == 0, "Unclosed calendar alarm."); return result
    }
    private fun topLevel(properties: List<Property>): List<Property> {
        var depth = 0
        return properties.filter { when (it.name) { "BEGIN" -> { depth++; false }; "END" -> { depth--; false }; else -> depth == 0 } }
    }
    private fun ruleParts(value: String, start: Property, resolver: Resolver, default: ZoneId): Map<String, String> {
        val parts = linkedMapOf<String, String>()
        val allowed = setOf("FREQ", "UNTIL", "COUNT", "INTERVAL", "BYSECOND", "BYMINUTE", "BYHOUR", "BYDAY", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH", "BYSETPOS", "WKST")
        for (field in upper(value).split(';')) {
            val pair = field.split('=', limit = 2)
            requireExport(pair.size == 2 && pair[1].isNotEmpty() && pair[0] in allowed && !parts.containsKey(pair[0]), "Invalid recurrence rule.")
            parts[pair[0]] = pair[1]
        }
        requireExport(parts["FREQ"] in setOf("SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY") && !(parts.containsKey("COUNT") && parts.containsKey("UNTIL")), "Unsupported or inconsistent recurrence rule.")
        for (key in listOf("INTERVAL", "COUNT")) parts[key]?.let { requireExport(it.toLongOrNull()?.let { n -> n in 1..9_007_199_254_740_991L } == true, "Invalid recurrence count/interval.") }
        for ((key, bounds) in mapOf("BYSECOND" to (0..60), "BYMINUTE" to (0..59), "BYHOUR" to (0..23), "BYMONTHDAY" to (-31..31), "BYYEARDAY" to (-366..366), "BYWEEKNO" to (-53..53), "BYMONTH" to (1..12), "BYSETPOS" to (-366..366))) {
            parts[key]?.split(',')?.forEach { token -> val number = token.toIntOrNull(); requireExport(number != null && number in bounds && (bounds.first == 0 || number != 0), "Invalid recurrence selector.") }
        }
        parts["BYDAY"]?.let { requireExport(it.split(',').all { field -> matches(field, "(?:[+-]?(?:[1-9]|[1-4][0-9]|5[0-3]))?(?:MO|TU|WE|TH|FR|SA|SU)") }, "Invalid recurrence weekday.") }
        parts["WKST"]?.let { requireExport(it in days, "Invalid recurrence week start.") }
        parts["UNTIL"]?.let {
            val initial = resolver.clock(start, default)
            val untilHeader = if (it.length == 8) ";VALUE=DATE" else if (!it.endsWith('Z') && !initial.floating && initial.source != "@utc") ";TZID=" + initial.source else ""
            val ending = resolver.clock(Property("DTSTART$untilHeader:$it"), default)
            requireExport(ending.dateOnly == initial.dateOnly && ending.instant >= initial.instant, "Recurrence end contradicts its start.")
        }
        return parts
    }
    private fun recurrence(record: JSONObject, start: Property, resolver: Resolver): List<String> {
        if (!record.has("wiederholung")) return emptyList()
        val repetition = record.opt("wiederholung"); requireExport(repetition is JSONObject, "Invalid structured recurrence.")
        val value = repetition as JSONObject
        requireExport(!value.has("art") || value.get("art") is String, "Invalid recurrence frequency.")
        requireExport(value.keys().asSequence().all { it in setOf("art", "bis", "intervall", "ordinal", "wochentag", "rruleForm", "daten") }, "Unsupported recurrence fields.")
        val type = text(value, "art")
        if (type.isEmpty() || type == "none") { requireExport(value.keys().asSequence().all { it == "art" || !meaningful(value.get(it)) }, "Contradictory recurrence."); return emptyList() }
        val display = displayZone(record); val source = resolver.clock(start, display)
        if (type == "custom") {
            val dates = strings(value.opt("daten")); requireExport(dates.isNotEmpty(), "Custom recurrence dates are missing.")
            val header = start.header.replaceFirst("DTSTART", "RDATE")
            return listOf(header + ":" + dates.distinct().sorted().joinToString(",") { day(it); it.replace("-", "") + (if (source.dateOnly) "" else start.value.drop(8)) })
        }
        val frequency = mapOf("daily" to "DAILY", "weekly" to "WEEKLY", "monthly" to "MONTHLY", "yearly" to "YEARLY")[type] ?: throw ExportException("Unsupported recurrence frequency.")
        var rule = "FREQ=$frequency"
        if (value.has("intervall")) { val interval = integer(value.get("intervall"), 1); requireExport(interval in 1..3660, "Invalid recurrence interval."); if (interval > 1) rule += ";INTERVAL=$interval" }
        if (value.has("ordinal") || value.has("wochentag")) {
            val ordinal = integer(value.opt("ordinal"), 0); val weekday = text(value, "wochentag")
            requireExport(type == "monthly" && ordinal in setOf(-1L, 1L, 2L, 3L, 4L) && weekday in days && text(value, "rruleForm") in setOf("", "bysetpos"), "Invalid ordinal monthly recurrence.")
            rule += if (text(value, "rruleForm") == "bysetpos") ";BYDAY=$weekday;BYSETPOS=$ordinal" else ";BYDAY=$ordinal$weekday"
        }
        val until = text(value, "bis")
        if (until.isNotEmpty()) {
            val date = day(until)
            val ending = if (source.dateOnly) until.replace("-", "") else {
                val lastWall = date.atTime(source.wall.toLocalTime())
                val instant = resolver.instant(lastWall, source.source, display)
                if (source.floating) lastWall.format(stamp) else Instant.ofEpochSecond(instant).atOffset(ZoneOffset.UTC).format(stamp) + "Z"
            }
            rule += ";UNTIL=$ending"
        }
        return listOf("RRULE:$rule")
    }
    private fun validateProjection(source: Clock, name: String, record: JSONObject, kind: Kind) {
        val dateField = if (kind == Kind.tasks) { if (name == "DTSTART") "startDatum" else "faellig" } else if (name == "DTSTART") "datum" else "endDatum"
        val timeField = if (kind == Kind.tasks) { if (name == "DTSTART") "startZeit" else "faelligZeit" } else if (name == "DTSTART") "zeit" else "endZeit"
        val storedDate = text(record, dateField).ifEmpty { if (kind == Kind.appointments) text(record, "datum") else "" }
        val storedTime = text(record, timeField).ifEmpty { if (kind == Kind.appointments && name == "DTEND" && record.opt("icsNullDauer") == true) text(record, "zeit") else "" }
        val instant = source.instant - if (source.dateOnly && kind == Kind.appointments && name == "DTEND") 86400 else 0
        val projected = Instant.ofEpochSecond(instant).atZone(if (source.dateOnly) utc else displayZone(record))
        val time = projected.format(DateTimeFormatter.ofPattern(if (storedTime.length == 8) "HH:mm:ss" else "HH:mm", Locale.ROOT))
        requireExport(storedDate.isNotEmpty() && projected.toLocalDate().toString() == storedDate && (if (source.dateOnly) storedTime.isEmpty() else time == storedTime), "Source calendar times contradict the visible record; export was cancelled.")
    }
    private val anniversaryNames = mapOf("birthday" to "Geburtstag", "death-anniversary" to "Todestag", "wedding-anniversary" to "Hochzeitstag", "partnership-anniversary" to "Partnerschaftstag", "name-day" to "Namenstag", "baptism" to "Tauftag", "first-communion" to "Kommunion", "confirmation" to "Konfirmation", "catholic-confirmation" to "Firmung", "anniversary" to "Jubiläum", "club-anniversary" to "Vereinsjubiläum", "work-anniversary" to "Dienstjubiläum", "founding-day" to "Gründungstag", "memorial-day" to "Gedenktag", "other" to "Sonstiges")
    private data class Parent(val original: String, val source: String, val wire: String)
    private fun component(record: JSONObject, kind: Kind, wireUID: String, parent: Parent?, resolver: Resolver): List<String> {
        validateRecord(record, kind)
        val sources = raw(record)
        validateSourceDisplay(record)
        if (kind == Kind.appointments) validateAlarms(record,sources)
        val top = topLevel(sources); val display = displayZone(record)
        val generated = mutableListOf("UID:" + escape(wireUID), "DTSTAMP:" + Instant.now().atOffset(ZoneOffset.UTC).format(stamp) + "Z")
        val title = text(record, if (kind == Kind.anniversaries) "name" else "titel"); requireExport(title.isNotEmpty(), "Calendar records need a title.")
        generated.add("SUMMARY:" + escape(title))
        val zoneName = text(record, "icsAnzeigeZeitzone")
        when (kind) {
            Kind.appointments -> {
                val start = text(record, "datum"); val startTime = text(record, "zeit"); val endDate = text(record, "endDatum").ifEmpty { start }; val endTime = text(record, "endZeit")
                day(start); day(endDate); requireExport(record.opt("ganztag") != true || startTime.isEmpty(), "Ambiguous all-day calendar record.")
                generated.add(timeLine("DTSTART", start, startTime, zoneName))
                if (startTime.isEmpty()) {
                    requireExport(endTime.isEmpty(), "An all-day event has a clock.")
                    val exclusive = day(endDate).plusDays(1); requireExport(exclusive.year in 1..9999, "All-day end is outside the supported range.")
                    generated.add("DTEND;VALUE=DATE:" + exclusive.format(DateTimeFormatter.BASIC_ISO_DATE))
                } else if (endTime.isNotEmpty()) generated.add(timeLine("DTEND", endDate, endTime, zoneName))
                else if (top.none { it.name == "DURATION" } && record.opt("icsEndeFehlt") != true) {
                    val instant = ordinaryWall(wall(start, startTime), display) + if (record.opt("icsNullDauer") == true) 0 else 1800
                    val end = Instant.ofEpochSecond(instant).atZone(display)
                    generated.add(timeLine("DTEND", end.toLocalDate().toString(), end.toLocalTime().format(DateTimeFormatter.ofPattern("HH:mm:ss", Locale.ROOT)), zoneName))
                }
            }
            Kind.tasks -> {
                for ((dateField, timeField, name) in listOf(Triple("startDatum", "startZeit", "DTSTART"), Triple("faellig", "faelligZeit", "DUE"))) {
                    if (text(record, dateField).isNotEmpty()) generated.add(timeLine(name, text(record, dateField), text(record, timeField), zoneName))
                    else requireExport(text(record, timeField).isEmpty(), "A task clock has no date.")
                }
                val priority = integer(record.opt("prio"), 2); requireExport(priority in 1..3, "Invalid task priority.")
                generated.add("PRIORITY:" + mapOf(1L to "1", 2L to "5", 3L to "9").getValue(priority))
                if (record.opt("erledigt") == true) generated.addAll(listOf("STATUS:COMPLETED", "PERCENT-COMPLETE:100"))
                if (record.opt("erinnern") == true) generated.add("X-MAGNOLIE-ERINNERUNG-AM-TAG:1")
                val originalParent = parent?.original ?: text(record, "icsElternUid").ifEmpty { text(record, "elternUid") }
                val wireParent = parent?.wire ?: originalParent
                if (wireParent.isNotEmpty()) generated.add("RELATED-TO;RELTYPE=PARENT:" + escape(wireParent))
                val order = integer(record.opt("reihenfolge"), 0); requireExport(order >= 0, "Invalid task order."); generated.add("X-MAGNOLIE-REIHENFOLGE:$order")
                val identity = JSONObject().put("v", 1).put("source", text(record, "icsQuelleId")).put("uid", identifier(record)).put("parent", originalParent)
                    .put("parentSource", parent?.source ?: (record.opt("icsElternQuelleId") as? String ?: text(record, "icsQuelleId")))
                generated.add("X-MAGNOLIE-TASK-IDENTITY:" + escape(identity.toString()))
            }
            Kind.anniversaries -> {
                val sourceDate = text(record, "datum"); val date = if (sourceDate.startsWith("--")) "2000-" + sourceDate.drop(2) else sourceDate
                day(date); generated.add("DTSTART;VALUE=DATE:" + date.replace("-", "")); generated.add("RRULE:FREQ=YEARLY")
                if (sourceDate.startsWith("--")) generated.add("X-MAGNOLIE-DATE:$sourceDate")
                val type = text(record, "typ").ifEmpty { "other" }; val legacy = anniversaryNames[type] ?: type
                generated.addAll(listOf("CATEGORIES:" + escape(legacy), "X-MAGNOLIE-TYPE-ID:" + (if (type in anniversaryNames) type else "custom"), "X-MAGNOLIE-TYP:" + escape(legacy), "X-MAGNOLIE-JAHRESTAG-TYP:" + escape(type)))
            }
        }
        for ((field, name) in listOf("notiz" to "DESCRIPTION", "ort" to "LOCATION", "kategorien" to "CATEGORIES", "kostenstelle" to "X-MAGNOLIE-KOSTENSTELLE", "kunde" to "X-MAGNOLIE-KUNDE")) if (text(record, field).isNotEmpty()) generated.add(name + ":" + escape(text(record, field)))
        if (record.opt("vertraulich") == true) generated.add("CLASS:CONFIDENTIAL")
        if (record.opt("vorlaeufig") == true) generated.add("STATUS:TENTATIVE")
        if (text(record, "icsStatus").isNotEmpty()) { generated.removeAll { it.startsWith("STATUS:") }; generated.add("STATUS:" + text(record, "icsStatus")) }
        val accent = text(record, "akzentFarbe")
        if (accent.isNotEmpty()) { requireExport(matches(accent, "#[0-9a-fA-F]{6}"), "Invalid calendar accent color."); generated.add("X-MAGNOLIE-ACCENT-COLOR:" + accent.lowercase(Locale.ROOT)) }
        val reminder = integer(record.opt("individuelleErinnerungTage"), 0); requireExport(reminder in 0..7, "Invalid custom calendar reminder.")
        if (reminder > 0) generated.add("X-MAGNOLIE-ERINNERUNG-TAGE:$reminder")
        if (record.opt("standardErinnerung") == false) generated.add("X-MAGNOLIE-STANDARDERINNERUNG:0")
        if (record.has("icsSequence")) { val sequence = integer(record.get("icsSequence"), 0); requireExport(sequence >= 0, "Invalid calendar revision."); generated.add("SEQUENCE:$sequence") }
        val byName = linkedMapOf<String, Property>()
        for (line in generated) { val property = Property(line); requireExport(!byName.containsKey(property.name), "Conflicting structured calendar fields."); byName[property.name] = property }
        val start = top.firstOrNull { it.name == "DTSTART" } ?: byName["DTSTART"]
        for (property in top) {
            if (property.name == "RELATED-TO" && upper(property.parameters["RELTYPE"] ?: "") != "PARENT") continue
            when (property.name) {
                "DTSTART", "DTEND", "DUE" -> {
                    if (kind != Kind.anniversaries) validateProjection(resolver.clock(property, display), property.name, record, kind)
                    else byName[property.name]?.let { requireExport(it.line == property.line, "Anniversary source date contradicts its visible date.") }
                }
                "DURATION" -> {
                    requireExport(start != null && top.none { it.name in setOf("DTEND", "DUE") }, "Ambiguous source calendar duration.")
                    val source = resolver.clock(start!!, display); val end = resolver.duration(property.value, source, display)
                    validateProjection(end, if (kind == Kind.tasks) "DUE" else "DTEND", record, kind)
                    byName.remove(if (kind == Kind.tasks) "DUE" else "DTEND")
                }
                else -> byName[property.name]?.let { own ->
                    if (property.name !in setOf("RRULE", "X-MAGNOLIE-TASK-IDENTITY")) {
                        if (kind == Kind.tasks && property.name == "PRIORITY") {
                            val priority = property.value.toIntOrNull(); requireExport(priority != null && priority in 0..9, "Invalid source task priority.")
                            val bucket = if (priority!! in 1..3) 1L else if (priority >= 7) 3L else 2L
                            requireExport(bucket == integer(record.opt("prio"), 2), "Source priority contradicts the visible task.")
                        } else if (kind == Kind.appointments && property.name == "CLASS" && record.opt("vertraulich") == true) requireExport(upper(property.value) in setOf("PRIVATE", "CONFIDENTIAL"), "Source confidentiality contradicts the visible appointment.")
                        else if (kind == Kind.tasks && property.name == "RELATED-TO" && parent != null) requireExport(unescape(property.value) in setOf(parent.original, parent.wire), "Source task parent contradicts its visible identity.")
                        else requireExport(unescape(property.value) == unescape(own.value), "Raw calendar data contradicts its visible fields.")
                    }
                }
            }
            if (property.name in setOf("RRULE", "EXRULE")) { requireExport(start != null, "Recurrence has no DTSTART."); ruleParts(property.value, start!!, resolver, display) }
            if (property.name in setOf("RDATE", "EXDATE", "RECURRENCE-ID")) {
                requireExport(start != null, "Recurrence dates have no DTSTART."); val initial = resolver.clock(start!!, display)
                for (value in property.value.split(',')) {
                    if (property.parameters["VALUE"] == "PERIOD") {
                        requireExport(property.name == "RDATE", "Only RDATE supports PERIOD values.")
                        val pair = value.split('/', limit = 2); requireExport(pair.size == 2, "Invalid recurrence period.")
                        val params = property.parameters.filterKeys { it != "VALUE" }.entries.joinToString("") { ";" + it.key + "=" + it.value }
                        val first = resolver.clock(Property("DTSTART$params:" + pair[0]), display)
                        val last = if (pair[1].startsWith("P") || pair[1].startsWith("+P")) resolver.duration(pair[1], first, display) else resolver.clock(Property("DTSTART$params:" + pair[1]), display)
                        requireExport(last.instant > first.instant && !initial.dateOnly, "Invalid recurrence period.")
                    } else { val candidate = resolver.clock(Property(property.header + ":" + value), display); requireExport(candidate.dateOnly == initial.dateOnly, "Recurrence value types do not match DTSTART.") }
                }
            }
            // Keep generated source-bound identities and rewritten task aliases;
            // original identity metadata is regenerated from qualified fields.
            if (!(kind == Kind.tasks && property.name in setOf("UID", "RELATED-TO", "X-MAGNOLIE-TASK-IDENTITY"))) byName.remove(property.name)
        }
        if (kind != Kind.anniversaries && start != null) {
            val desired = recurrence(record, start, resolver); val rawRule = top.firstOrNull { it.name == "RRULE" }
            val generatedRule = desired.firstOrNull { it.startsWith("RRULE:") }
            if (rawRule != null && generatedRule != null) {
                val wanted = ruleParts(generatedRule.drop(6), start, resolver, display); val actual = ruleParts(rawRule.value, start, resolver, display)
                requireExport(wanted.all { actual[it.key] == it.value } && actual["COUNT"] == null, "Structured recurrence contradicts the source RRULE.")
                val source = resolver.clock(start, display); val date = source.wall.toLocalDate()
                for ((key, value) in actual.filterKeys { it !in wanted }) {
                    val redundant = key == "INTERVAL" && value == "1" || key == "WKST" || key == "BYDAY" && wanted["FREQ"] == "WEEKLY" && value == days[date.dayOfWeek.value % 7] ||
                        key == "BYMONTHDAY" && wanted["FREQ"] in setOf("MONTHLY", "YEARLY") && value == date.dayOfMonth.toString() || key == "BYMONTH" && wanted["FREQ"] == "YEARLY" && value == date.monthValue.toString()
                    requireExport(redundant, "Source recurrence has selectors absent from the visible recurrence.")
                }
            } else if (rawRule == null) for (line in desired) { val property = Property(line); if (top.none { it.name == property.name }) byName[property.name] = property }
            if (record.has("icsAusnahmen")) {
                val exceptions = strings(record.get("icsAusnahmen")); val rawDates = top.filter { it.name == "EXDATE" }.flatMap { property ->
                    property.value.split(',').map {
                        val source = resolver.clock(Property(property.header + ":" + it), display)
                        Instant.ofEpochSecond(source.instant).atZone(if (source.dateOnly) utc else display).toLocalDate().toString()
                    }
                }.toSet()
                val missing = exceptions.distinct().sorted().filter { it !in rawDates }
                if (missing.isNotEmpty()) {
                    val source = resolver.clock(start, display)
                    val time = if (source.dateOnly) "" else Instant.ofEpochSecond(source.instant).atZone(display).format(DateTimeFormatter.ofPattern("HH:mm:ss", Locale.ROOT))
                    val additions = missing.map { Property(timeLine("EXDATE", it, time, if (source.floating) "" else text(record, "icsAnzeigeZeitzone"))) }
                    byName["EXDATE"] = Property(additions.first().header + ":" + additions.joinToString(",") { it.value })
                }
            }
        }
        if (start == null && record.has("wiederholung")) {
            val repetition = record.opt("wiederholung")
            requireExport(repetition is JSONObject && text(repetition, "art") in setOf("", "none") &&
                repetition.keys().asSequence().all { it == "art" || !meaningful(repetition.opt(it)) },
                "A recurring calendar item has no DTSTART.")
        }
        val endName = if (kind == Kind.tasks) "DUE" else "DTEND"
        val end = (top.firstOrNull { it.name == endName } ?: byName[endName])?.let { resolver.clock(it, display) }
        if (start != null && end != null) requireExport(end.instant >= resolver.clock(start, display).instant, "Calendar end precedes start.")
        val type = if (kind == Kind.tasks) "VTODO" else "VEVENT"
        val output = mutableListOf("BEGIN:$type")
        for (line in generated) byName.remove(Property(line).name)?.let { output.add(it.line) }
        for (key in byName.keys.sorted()) output.add(byName.getValue(key).line)
        // Source task identities/parent links must not duplicate rewritten
        // source-qualified generated properties, including inside alias batches.
        var alarm = 0
        for (property in sources) {
            if (property.name == "BEGIN") alarm++
            val rewritten = kind == Kind.tasks && alarm == 0 && (property.name == "UID" || property.name == "X-MAGNOLIE-TASK-IDENTITY" || property.name == "RELATED-TO" && upper(property.parameters["RELTYPE"] ?: "") == "PARENT")
            if (!rewritten) output.add(property.line)
            if (property.name == "END") alarm--
        }
        output.add("END:$type"); return output
    }
    private fun definitions(records: List<JSONObject>, check: () -> Unit): MutableMap<String, List<String>> {
        val definitions = linkedMapOf<String, List<String>>()
        var total = 0L
        for (record in records) {
            check()
            record.opt("icsTimezones")?.let { value ->
                requireExport(value is JSONArray, "Invalid source time-zone definitions.")
                val blocks = value as JSONArray
                for (index in 0 until blocks.length()) {
                    val block = strings(blocks.get(index)); requireExport(block.firstOrNull() == "BEGIN:VTIMEZONE" && block.lastOrNull() == "END:VTIMEZONE", "Invalid source time-zone component.")
                    val properties = block.map(::Property); val names = properties.filter { it.name == "TZID" }
                    requireExport(names.size == 1 && names[0].value.isNotEmpty(), "Missing or duplicate source TZID.")
                    val stack = mutableListOf<String>()
                    for (property in properties) {
                        if (property.name == "BEGIN") {
                            requireExport(if (stack.isEmpty()) property.value == "VTIMEZONE" else stack.size == 1 && property.value in setOf("STANDARD", "DAYLIGHT"), "Invalid time-zone component nesting.")
                            stack.add(property.value)
                        } else if (property.name == "END") {
                            requireExport(stack.isNotEmpty() && stack.removeAt(stack.lastIndex) == property.value, "Unbalanced source time-zone definition.")
                        }
                    }
                    requireExport(stack.isEmpty(), "Unclosed source time-zone definition.")
                    val name = names[0].value; val previous = definitions[name]
                    requireExport(previous == null || previous == block, "Conflicting source definitions share a TZID.")
                    if (previous == null) {
                        total += block.sumOf { it.toByteArray(Charsets.UTF_8).size.toLong() + 2 }
                        requireExport(total <= maximumBytes, "Source time zones exceed the export size limit.")
                        definitions[name] = block
                    }
                }
            }
        }
        return definitions
    }
    @JvmOverloads
    fun encode(records: List<JSONObject>, kind: String, defaultTimeZone: String = "system",
               checkCancelled: () -> Unit = { if (Thread.currentThread().isInterrupted) throw CancellationException("Calendar export cancelled.") }): String {
        val selected = Kind.entries.firstOrNull { it.wire == kind } ?: throw ExportException("Unsupported calendar export kind.")
        return encode(records, selected, defaultTimeZone, checkCancelled)
    }
    @JvmOverloads
    fun encode(input: List<JSONObject>, kind: Kind, defaultTimeZone: String = "system",
               checkCancelled: () -> Unit = { if (Thread.currentThread().isInterrupted) throw CancellationException("Calendar export cancelled.") }): String {
        checkCancelled(); requireExport(input.isNotEmpty() && input.size <= maximumRecords, "There are no calendar records to export or the record limit was exceeded.")
        var inputBytes = 0L
        // Own snapshots of the JSON records before constructing any output.
        // No output is returned or destination file opened by this pure codec.
        val records = input.map { record ->
            checkCancelled(); val encoded = record.toString()
            inputBytes += encoded.toByteArray(Charsets.UTF_8).size
            requireExport(inputBytes <= ICalendarImport.maximumProjectedBytes, "Calendar input exceeds the export projection limit.")
            JSONObject(encoded).also { if (text(it, "icsAnzeigeZeitzone").isEmpty()) it.put("icsAnzeigeZeitzone", defaultTimeZone) }
        }
        val definitions = definitions(records, checkCancelled); val resolver = Resolver(definitions, checkCancelled)
        val recordSources = records.groupBy { identifier(it) }.mapValues { (_, owners) -> owners.map { text(it, "icsQuelleId") }.toSet() }
        val pairs = records.map { text(it, "icsQuelleId") to identifier(it) }.toSet()
        val wireNames = linkedMapOf<Pair<String, String>, String>()
        val reserved = pairs.map { it.second }.toMutableSet()
        for (pair in pairs.sortedWith(compareBy<Pair<String, String>> { it.second }.thenBy { it.first })) {
            val collision = recordSources.getValue(pair.second).size > 1
            requireExport(!collision || kind == Kind.tasks, "Colliding source identities require source-aware task export.")
            var wire = pair.second
            if (collision) {
                val base = "urn:magnolie:task:" + hash(pair.first + "\u0000" + pair.second)
                wire = base; var suffix = 1
                while (wire in reserved) { wire = "$base-$suffix"; suffix++ }
                reserved.add(wire)
            }
            wireNames[pair] = wire
        }
        val identities = mutableSetOf<String>(); val components = mutableListOf<List<String>>(); var bodyBytes = 0L
        for (record in records) {
            checkCancelled(); val uid = identifier(record); val source = text(record, "icsQuelleId"); val properties = topLevel(raw(record))
            val recurrenceID = properties.firstOrNull { it.name == "RECURRENCE-ID" }?.line ?: "master"
            requireExport(identities.add(source + "\u0000" + uid + "\u0000" + recurrenceID), "Duplicate calendar component identity.")
            for (field in listOf("icsZusatzDaten", "icsZusatzTermine")) requireExport(!meaningful(record.opt(field)) || properties.any { it.name == "RDATE" }, "Additional occurrence metadata has no authoritative RDATE.")
            if (meaningful(record.opt("icsRangeOverrides"))) {
                val ranges = record.opt("icsRangeOverrides"); requireExport(ranges is JSONArray, "Invalid recurrence range bodies.")
                for (index in 0 until (ranges as JSONArray).length()) {
                    val range = strings(ranges.get(index))
                    requireExport(records.any { identifier(it) == uid && text(it, "icsQuelleId") == source && it.opt("icsRoundtrip")?.let(::strings) == range }, "Export the complete series including its range exceptions.")
                }
            }
            if (kind == Kind.tasks && record.has("erinnerungsMinute")) requireExport(integer(record.get("erinnerungsMinute"), 480) == 480L, "A custom task reminder clock requires a complete JSON backup.")
            var parent: Parent? = null
            if (kind == Kind.tasks) {
                val original = text(record, "icsElternUid").ifEmpty { text(record, "elternUid") }
                val parentSource = record.opt("icsElternQuelleId") as? String ?: source
                if (original.isNotEmpty()) {
                    val candidates = records.filter { text(it, "icsQuelleId") == parentSource && (text(it, "uid") == text(record, "elternUid") || identifier(it) == original) }
                        .distinctBy { identifier(it) }
                    requireExport(candidates.size <= 1, "Ambiguous source-qualified task parent.")
                    val parentUID = candidates.firstOrNull()?.let(::identifier) ?: original
                    parent = Parent(parentUID, parentSource, wireNames[parentSource to parentUID] ?: parentUID)
                }
            }
            val lines = component(record, kind, wireNames.getValue(source to uid), parent, resolver)
            bodyBytes += lines.sumOf { it.toByteArray(Charsets.UTF_8).size.toLong() + 2 }
            requireExport(bodyBytes <= maximumBytes, "Calendar export exceeds 32 MiB.")
            components.add(lines)
        }
        val referenced = components.flatMap { lines -> lines.mapNotNull { Property(it).parameters["TZID"] } }.toSet()
        for (name in referenced.sorted()) if (!definitions.containsKey(name)) definitions[name] = TimeZoneExport.definition(name, checkCancelled)
        val lines = mutableListOf("BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Magnolie Organizer Android Tablet Beta//EN", "CALSCALE:GREGORIAN")
        for (name in definitions.keys.sorted()) lines.addAll(definitions.getValue(name))
        components.forEach { lines.addAll(it) }; lines.add("END:VCALENDAR")
        val output = StringBuilder(); var outputBytes = 0L
        for (line in lines) {
            checkCancelled(); var width = 0
            // Code points keep surrogate pairs / UTF-8 sequences intact. Every
            // continuation's leading space counts toward the RFC 75-octet limit.
            var index = 0
            while (index < line.length) {
                val code = line.codePointAt(index); val piece = String(Character.toChars(code))
                requireExport(code !in 0xD800..0xDFFF, "Invalid Unicode in calendar output.")
                val size = piece.toByteArray(Charsets.UTF_8).size
                if (width + size > 75) { output.append("\r\n "); outputBytes += 3; width = 1 }
                output.append(piece); width += size; outputBytes += size
                requireExport(outputBytes + 2 <= maximumBytes, "Calendar export exceeds 32 MiB.")
                index += Character.charCount(code)
            }
            output.append("\r\n"); outputBytes += 2
        }
        checkCancelled(); return output.toString()
    }
}
