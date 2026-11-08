package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest
import java.text.Normalizer
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.concurrent.CancellationException

/** Pure, bounded, whole-file import. Source recurrence properties stay authoritative;
 * this codec never expands event occurrences and never modifies storage or accounts. */
object ICalendarImport {
    const val maximumBytes = 32 * 1024 * 1024
    const val maximumRecords = 50_000
    const val maximumProjectedBytes = 96 * 1024 * 1024
    class ImportException(message: String) : IllegalArgumentException(message)
    data class Result(
        val appointments: List<JSONObject>, val tasks: List<JSONObject>, val anniversaries: List<JSONObject>,
        val calendarProperties: List<String>, val sourceSHA256: String
    ) {
        val document: JSONObject get() = JSONObject().put("termine", JSONArray(appointments))
            .put("aufgaben", JSONArray(tasks)).put("jahrestage", JSONArray(anniversaries))
            .put("icsImportMetadata", JSONObject().put("version", 1)
                .put("calendarProperties", JSONArray(calendarProperties)).put("sourceSHA256", sourceSHA256))
    }
    private fun requireImport(condition: Boolean, message: String) { if (!condition) throw ImportException(message) }
    private fun matches(text: String, pattern: String) = Regex(pattern).matches(text)
    private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
    private fun hash(text: String) = hash(text.toByteArray(Charsets.UTF_8))
    private fun upper(value: String) = value.uppercase(Locale.ROOT)
    private fun integer(text: String, fallback: Long = 0): Long {
        if (text.isEmpty()) return fallback
        val n = text.toLongOrNull() ?: throw ImportException("Invalid calendar integer.")
        requireImport(n in -9_007_199_254_740_991L..9_007_199_254_740_991L, "Calendar integer exceeds the supported range.")
        return n
    }
    private fun unescape(value: String): String = buildString {
        var escaped = false
        for (c in value) {
            if (escaped) { append(if (c == 'n' || c == 'N') '\n' else c); escaped = false }
            else if (c == '\\') escaped = true else append(c)
        }
        if (escaped) append('\\')
    }
    private class Property(val line: String) {
        val name: String
        val header: String
        val value: String
        val parameters = linkedMapOf<String, String>()
        init {
            requireImport(line.isNotEmpty() && line.none { it == '\u0000' || it == '\r' || it == '\n' }, "Invalid calendar content line.")
            var quoted = false
            var separator = -1
            for (i in line.indices) {
                if (line[i] == '"') quoted = !quoted
                else if (line[i] == ':' && !quoted) { separator = i; break }
            }
            requireImport(separator >= 0 && !quoted, "Invalid calendar property header.")
            header = line.substring(0, separator); value = line.substring(separator + 1)
            val fields = mutableListOf<String>(); val field = StringBuilder(); quoted = false
            for (c in header) {
                if (c == '"') quoted = !quoted
                if (c == ';' && !quoted) { fields.add(field.toString()); field.setLength(0) } else field.append(c)
            }
            fields.add(field.toString())
            requireImport(matches(fields.first(), "[A-Za-z0-9-]+"), "Invalid calendar property name.")
            name = upper(fields.first())
            for (part in fields.drop(1)) {
                val pair = part.split('=', limit = 2)
                requireImport(pair.size == 2 && matches(pair[0], "[A-Za-z0-9-]+") && !parameters.containsKey(upper(pair[0])), "Invalid calendar parameter.")
                var text = pair[1]
                if (text.startsWith('"')) {
                    requireImport(text.length >= 2 && text.endsWith('"'), "Invalid quoted calendar parameter.")
                    text = text.substring(1, text.lastIndex)
                }
                parameters[upper(pair[0])] = text
            }
        }
        fun renamed(name: String, removing: Set<String> = emptySet()): String = name + parameters.keys.sorted().filter { it !in removing }.joinToString("") {
            val value = parameters.getValue(it)
            ";$it=" + if (value.any { c -> c == ':' || c == ';' || c == ',' }) "\"$value\"" else value
        } + ":" + value
    }
    private class Component(val name: String, line: String) {
        val properties = mutableListOf<Property>()
        val children = mutableListOf<Component>()
        val lines = mutableListOf(line)
        fun property(name: String) = properties.firstOrNull { it.name == name }
        fun value(name: String) = property(name)?.value?.let(::unescape) ?: ""
    }
    private fun unfold(text: String, check: () -> Unit): List<String> {
        requireImport('\u0000' !in text, "Calendar files cannot contain NUL bytes.")
        val normalized = text.replace("\r\n", "\n")
        // Enforce the physical-line budget before split can allocate millions
        // of substrings for a small, adversarial newline-only file.
        requireImport(normalized.count { it == '\n' } < 250_000, "Calendar file has too many lines.")
        val physical = normalized.split('\n')
        val lines = mutableListOf<String>()
        var current: StringBuilder? = null; var currentBytes = 0
        // Accumulate a folded property once. Repeated String concatenation and
        // UTF-8 recounting would make a valid many-fold property quadratic.
        for ((index, line) in physical.withIndex()) {
            if (index % 1024 == 0) check()
            requireImport(line.none { it == '\r' || it.code < 32 && it != '\t' }, "Invalid calendar control character.")
            if (line.startsWith(' ') || line.startsWith('\t')) {
                requireImport(current != null, "Calendar continuation has no preceding property.")
                val piece = line.drop(1)
                currentBytes += piece.toByteArray(Charsets.UTF_8).size
                requireImport(currentBytes <= 1024 * 1024, "Calendar content line is too large.")
                current!!.append(piece)
            } else if (line.isNotEmpty()) {
                current?.let { lines.add(it.toString()) }
                currentBytes = line.toByteArray(Charsets.UTF_8).size
                requireImport(currentBytes <= 1024 * 1024, "Calendar content line is too large.")
                current = StringBuilder(line)
            }
        }
        current?.let { lines.add(it.toString()) }
        return lines
    }
    private fun parse(lines: List<String>, check: () -> Unit): List<Component> {
        val stack = mutableListOf<Component>(); val roots = mutableListOf<Component>(); var count = 0
        val singleton = setOf("UID", "DTSTART", "DTEND", "DUE", "DURATION", "SUMMARY", "DESCRIPTION", "DTSTAMP", "LAST-MODIFIED", "RECURRENCE-ID", "SEQUENCE", "STATUS", "CLASS", "PRIORITY", "PERCENT-COMPLETE", "X-MAGNOLIE-TASK-IDENTITY")
        for ((index, line) in lines.withIndex()) {
            if (index % 1024 == 0) check()
            val property = Property(line)
            when (property.name) {
                "BEGIN" -> {
                    val parent = stack.lastOrNull()?.name
                    val allowed = when (parent) {
                        null -> setOf("VCALENDAR", "VEVENT", "VTODO")
                        "VCALENDAR" -> setOf("VEVENT", "VTODO", "VTIMEZONE")
                        "VTIMEZONE" -> setOf("STANDARD", "DAYLIGHT")
                        "VEVENT", "VTODO" -> setOf("VALARM")
                        else -> emptySet()
                    }
                    val name = upper(property.value)
                    requireImport(name in allowed && stack.size < 8 && count < maximumRecords, "Unsupported or excessively nested calendar component; nothing was imported.")
                    stack.forEach { it.lines.add(line) }
                    val component = Component(name, line)
                    if (stack.isEmpty()) roots.add(component) else stack.last().children.add(component)
                    stack.add(component); count++
                }
                "END" -> {
                    requireImport(stack.isNotEmpty() && stack.last().name == upper(property.value), "Calendar file is incomplete or unbalanced.")
                    stack.forEach { it.lines.add(line) }; stack.removeAt(stack.lastIndex)
                }
                else -> {
                    val current = stack.lastOrNull() ?: throw ImportException("Calendar property outside a component.")
                    requireImport(property.name !in singleton || current.property(property.name) == null, "Ambiguous duplicate calendar property.")
                    current.properties.add(property); stack.forEach { it.lines.add(line) }
                }
            }
        }
        requireImport(stack.isEmpty() && roots.isNotEmpty() && roots.count { it.name == "VCALENDAR" } <= 1 && (roots.size == 1 || roots.none { it.name == "VCALENDAR" }), "Import one complete calendar per transaction.")
        roots.firstOrNull()?.takeIf { it.name == "VCALENDAR" }?.let {
            requireImport(it.properties.count { p -> p.name == "VERSION" } == 1 && it.value("VERSION") == "2.0", "Only iCalendar VERSION 2.0 is supported.")
        }
        return roots
    }
    private const val absoluteUTC = "@magnolie-utc-instant"
    private val dayNames = listOf("SU", "MO", "TU", "WE", "TH", "FR", "SA")
    private data class Clock(val instant: Long, val wall: LocalDateTime, val dateOnly: Boolean, val source: String)
    private fun naive(text: String): LocalDateTime {
        val value = upper(text)
        requireImport(matches(value, "[0-9]{8}(?:T[0-9]{4}(?:[0-9]{2})?)?"), "Invalid calendar date/time.")
        try {
            val year = value.substring(0, 4).toInt()
            requireImport(year in 1..9999, "Invalid calendar year.")
            return LocalDateTime.of(year, value.substring(4, 6).toInt(), value.substring(6, 8).toInt(),
                if (value.length > 8) value.substring(9, 11).toInt() else 0,
                if (value.length > 8) value.substring(11, 13).toInt() else 0,
                if (value.length > 13) value.substring(13, 15).toInt() else 0)
        } catch (error: java.time.DateTimeException) { throw ImportException("Invalid calendar date/time.") }
    }
    private fun naiveSeconds(value: LocalDateTime) = value.toEpochSecond(ZoneOffset.UTC)
    private fun fromSeconds(value: Long) = LocalDateTime.ofEpochSecond(value, 0, ZoneOffset.UTC)
    private fun knownZone(name: String): ZoneId {
        requireImport(name.isNotEmpty() && name.toByteArray(Charsets.UTF_8).size <= 255, "Unresolved source time zone.")
        return try { ZoneId.of(name) } catch (_: java.time.DateTimeException) { throw ImportException("Unresolved source time zone.") }
    }
    private fun ordinaryWall(wall: LocalDateTime, zone: ZoneId): Long {
        val offsets = zone.rules.getValidOffsets(wall)
        requireImport(offsets.isNotEmpty(), "A calendar wall time falls in a daylight-saving gap.")
        return offsets.minOf { wall.toEpochSecond(it) } // RFC first occurrence in an overlap.
    }
    private fun ruleDictionary(value: String): Map<String, String> {
        val result = linkedMapOf<String, String>()
        val allowed = setOf("FREQ", "INTERVAL", "COUNT", "UNTIL", "BYSECOND", "BYMINUTE", "BYHOUR", "BYDAY", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH", "BYSETPOS", "WKST")
        for (field in upper(value).split(';')) {
            val pair = field.split('=', limit = 2)
            requireImport(pair.size == 2 && pair[1].isNotEmpty() && pair[0] in allowed && !result.containsKey(pair[0]), "Invalid or unsupported recurrence rule.")
            result[pair[0]] = pair[1]
        }
        requireImport(result["FREQ"] in setOf("SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY") && !(result.containsKey("COUNT") && result.containsKey("UNTIL")), "Invalid recurrence frequency/end.")
        for (key in listOf("COUNT", "INTERVAL")) result[key]?.let { requireImport(integer(it) > 0, "Invalid recurrence count/interval.") }
        for ((key, bounds) in mapOf("BYSECOND" to (0L..60L), "BYMINUTE" to (0L..59L), "BYHOUR" to (0L..23L), "BYMONTH" to (1L..12L), "BYMONTHDAY" to (-31L..31L), "BYYEARDAY" to (-366L..366L), "BYWEEKNO" to (-53L..53L), "BYSETPOS" to (-366L..366L))) {
            result[key]?.split(',')?.forEach {
                val n = integer(it)
                requireImport(it.isNotEmpty() && n in bounds && (bounds.first == 0L || n != 0L), "Invalid recurrence selector.")
            }
        }
        result["BYDAY"]?.let { requireImport(it.split(',').all { day -> matches(day, "(?:[+-]?(?:[1-9]|[1-4][0-9]|5[0-3]))?(?:MO|TU|WE|TH|FR|SA|SU)") }, "Invalid recurrence weekday.") }
        result["WKST"]?.let { requireImport(it in dayNames, "Invalid recurrence week start.") }
        result["UNTIL"]?.let { naive(it.removeSuffix("Z")) }
        return result
    }
    /** Manual UTC seconds permit RFC 5545 offsets up to 23:59:59 without the
     * narrower +/-18h java.time.ZoneOffset limit or any invented OS zone. */
    private class EmbeddedZone(component: Component, private val check: () -> Unit) {
        data class Observation(val start: LocalDateTime, val before: Int, val after: Int, val dates: List<LocalDateTime>, val rule: Map<String, String>)
        private val observations: List<Observation>
        private val cached = linkedMapOf<Int, List<Pair<Long, Int>>>()
        companion object {
            fun offset(value: String): Int {
                requireImport(matches(value, "[+-][0-9]{4}(?:[0-9]{2})?"), "Invalid embedded time-zone offset.")
                val hour = value.substring(1, 3).toInt(); val minute = value.substring(3, 5).toInt()
                val second = if (value.length == 7) value.substring(5, 7).toInt() else 0
                requireImport(hour <= 23 && minute < 60 && second < 60, "Invalid embedded time-zone offset.")
                return (if (value[0] == '-') -1 else 1) * (hour * 3600 + minute * 60 + second)
            }
        }
        init {
            requireImport(component.children.isNotEmpty() && component.children.size <= 4096, "Invalid embedded time-zone observances.")
            observations = component.children.map { child ->
                check()
                val start = child.property("DTSTART") ?: throw ImportException("Incomplete embedded time-zone observance.")
                requireImport(child.name in setOf("STANDARD", "DAYLIGHT") && !upper(start.value).endsWith('Z') && child.properties.count { it.name == "TZOFFSETFROM" } == 1 && child.properties.count { it.name == "TZOFFSETTO" } == 1, "Incomplete embedded time-zone observance.")
                val before = offset(child.value("TZOFFSETFROM")); val after = offset(child.value("TZOFFSETTO"))
                val dates = mutableListOf<LocalDateTime>()
                for (property in child.properties.filter { it.name == "RDATE" }) {
                    requireImport(property.parameters.isEmpty(), "Unsupported embedded transition dates.")
                    dates.addAll(property.value.split(',').map(::naive))
                    requireImport(dates.size <= 50_000, "Too many embedded transition dates.")
                }
                val rules = child.properties.filter { it.name == "RRULE" }
                requireImport(rules.size <= 1, "Ambiguous embedded time-zone rule.")
                val rule = rules.firstOrNull()?.let { ruleDictionary(it.value) } ?: emptyMap()
                if (rule.isNotEmpty()) {
                    requireImport(rule["FREQ"] == "YEARLY" && rule["COUNT"] == null && rule["INTERVAL"] in listOf(null, "1") &&
                        (rule["BYMONTH"] != null || listOf("BYMONTHDAY", "BYDAY", "BYSETPOS").all { rule[it] == null }) &&
                        rule.keys.all { it in setOf("FREQ", "INTERVAL", "BYMONTH", "BYMONTHDAY", "BYDAY", "BYSETPOS", "UNTIL", "WKST") }, "This embedded time-zone rule cannot be resolved safely.")
                }
                Observation(naive(start.value), before, after, dates, rule)
            }
        }
        private fun ruleDates(observation: Observation, year: Int): List<LocalDateTime> {
            val rule = observation.rule
            if (rule.isEmpty() || year < observation.start.year) return emptyList()
            val months = rule["BYMONTH"]?.split(',')?.map { integer(it).toInt() }?.toSet() ?: setOf(observation.start.monthValue)
            val weekdays = rule["BYDAY"]?.split(',')?.toSet() ?: emptySet()
            val monthDays = rule["BYMONTHDAY"]?.split(',')?.map(::integer)?.toSet()
            var dates = mutableListOf<LocalDateTime>()
            for (month in months) {
                check()
                val length = LocalDate.of(year, month, 1).lengthOfMonth()
                for (day in 1..length) {
                    if (monthDays != null && day.toLong() !in monthDays && (day - length - 1).toLong() !in monthDays) continue
                    if (monthDays == null && weekdays.isEmpty() && day != observation.start.dayOfMonth) continue
                    val date = LocalDate.of(year, month, day).atTime(observation.start.toLocalTime())
                    if (weekdays.isNotEmpty()) {
                        val accepted = weekdays.any { selector ->
                            val wanted = dayNames.indexOf(selector.takeLast(2))
                            val number = selector.dropLast(2).let { if (it.isEmpty()) 0 else integer(it).toInt() }
                            date.dayOfWeek.value % 7 == wanted && (number == 0 || number > 0 && (day - 1) / 7 + 1 == number || number < 0 && -((length - day) / 7 + 1) == number)
                        }
                        if (!accepted) continue
                    }
                    if (date >= observation.start) dates.add(date)
                }
            }
            dates = dates.distinct().sorted().toMutableList()
            rule["BYSETPOS"]?.let { positions ->
                val selected = positions.split(',').mapNotNull {
                    val number = integer(it).toInt()
                    dates.getOrNull(if (number > 0) number - 1 else dates.size + number)
                }
                dates = selected.distinct().sorted().toMutableList()
            }
            rule["UNTIL"]?.let {
                val until = naiveSeconds(naive(it.removeSuffix("Z")))
                dates = dates.filter { date -> naiveSeconds(date) - (if (it.endsWith('Z')) observation.before else 0) <= until }.toMutableList()
            }
            return dates
        }
        private fun activeOffset(instant: Long): Int {
            val year = fromSeconds(instant).year
            requireImport(year in 1..9999, "Embedded time outside the supported range.")
            val transitions = cached[year] ?: run {
                val collected = mutableListOf<Pair<Long, Int>>()
                for (observation in observations) {
                    check()
                    val walls = mutableListOf(observation.start); walls.addAll(observation.dates)
                    if (observation.rule.isNotEmpty()) {
                        val years = ((maxOf(1, year - 1))..minOf(9999, year + 1)).toMutableSet()
                        observation.rule["UNTIL"]?.let {
                            val end = naive(it.removeSuffix("Z")).year
                            years.addAll(maxOf(1, end - 1)..minOf(9999, end + 1))
                        }
                        for (candidate in years.sorted()) walls.addAll(ruleDates(observation, candidate))
                    }
                    collected.addAll(walls.map { (naiveSeconds(it) - observation.before) to observation.after })
                }
                collected.sortBy { it.first }
                for (i in 1 until collected.size) requireImport(collected[i].first != collected[i - 1].first || collected[i].second == collected[i - 1].second, "Conflicting embedded time-zone transitions.")
                if (cached.size >= 64) cached.clear()
                cached[year] = collected; collected
            }
            var low = 0; var high = transitions.size
            while (low < high) { val mid = (low + high) / 2; if (transitions[mid].first <= instant) low = mid + 1 else high = mid }
            return if (low > 0) transitions[low - 1].second else observations.minBy { naiveSeconds(it.start) - it.before }.before
        }
        fun instant(wall: LocalDateTime): Long {
            val candidates = observations.flatMap { listOf(it.before, it.after) }.toSet().mapNotNull { offset ->
                val candidate = naiveSeconds(wall) - offset
                if (activeOffset(candidate) == offset) candidate else null
            }
            return candidates.minOrNull() ?: throw ImportException("A source time falls in an embedded time-zone gap.")
        }
    }
    private class Resolver(val display: ZoneId, val displayName: String, val zones: Map<String, EmbeddedZone>) {
        fun instant(wall: LocalDateTime, source: String): Long = when {
            source == absoluteUTC -> naiveSeconds(wall)
            zones.containsKey(source) -> zones.getValue(source).instant(wall)
            else -> ordinaryWall(wall, if (source.isEmpty()) display else knownZone(source))
        }
        fun clock(property: Property): Clock {
            val value = upper(property.value.trim())
            val dateOnly = upper(property.parameters["VALUE"] ?: "") == "DATE" || matches(value, "[0-9]{8}")
            if (dateOnly) {
                requireImport(matches(value, "[0-9]{8}") && property.parameters["TZID"] == null, "Invalid date-only source property.")
                val date = naive(value); return Clock(naiveSeconds(date), date, true, absoluteUTC)
            }
            requireImport(property.parameters["VALUE"]?.let { upper(it) in setOf("DATE-TIME") } != false && matches(value, "[0-9]{8}T[0-9]{4}(?:[0-9]{2})?Z?") && (!value.endsWith('Z') || property.parameters["TZID"] == null), "Invalid source calendar date-time.")
            val source = if (value.endsWith('Z')) absoluteUTC else property.parameters["TZID"] ?: ""
            val wall = naive(value.removeSuffix("Z")); val resolved = instant(wall, source)
            requireImport(java.time.Instant.ofEpochSecond(resolved).atZone(display).year in 1..9999, "Calendar time is outside the supported display range.")
            return Clock(resolved, wall, false, source)
        }
        fun duration(specification: String, start: Clock): Clock {
            val m = Regex("\\+?P(?:(\\d+)W|(?:(\\d+)D)?(?:T(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+)S)?)?)").matchEntire(specification)
                ?: throw ImportException("Invalid calendar duration.")
            val values = (1..5).map { i -> m.groups[i]?.value?.let { integer(it) } ?: 0 }
            requireImport((1..5).any { m.groups[it] != null } && values.all { it in 0..1_000_000 } && (!start.dateOnly || values.drop(2).all { it == 0L }), "Invalid or excessive calendar duration.")
            val wall = start.wall.plusDays(values[0] * 7 + values[1])
            val exact = values[2] * 3600 + values[3] * 60 + values[4]
            val end = instant(wall, start.source) + exact
            val projected = java.time.Instant.ofEpochSecond(end).atZone(if (start.dateOnly) ZoneOffset.UTC else display)
            requireImport(projected.year in 1..9999, "Calendar duration is outside the supported range.")
            return Clock(end, wall.plusSeconds(exact), start.dateOnly, start.source)
        }
        fun date(clock: Clock) = java.time.Instant.ofEpochSecond(clock.instant).atZone(if (clock.dateOnly) ZoneOffset.UTC else display).toLocalDate().toString()
        fun time(clock: Clock) = if (clock.dateOnly) "" else java.time.Instant.ofEpochSecond(clock.instant).atZone(display).format(DateTimeFormatter.ofPattern("HH:mm", Locale.ROOT))
    }
    private fun simpleRule(fields: Map<String, String>, start: Clock, resolver: Resolver): Map<String, Any>? {
        val type = mapOf("DAILY" to "daily", "WEEKLY" to "weekly", "MONTHLY" to "monthly", "YEARLY" to "yearly")[fields["FREQ"]] ?: return null
        if (!setOf("FREQ", "INTERVAL", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST").containsAll(fields.keys)) return null
        val interval = integer(fields["INTERVAL"] ?: "1")
        if (interval !in 1..3660 || type !in setOf("daily", "weekly") && interval != 1L) return null
        val date = LocalDate.parse(resolver.date(start)); var ordinal: Long? = null; var weekday = ""
        when (type) {
            "daily" -> if (listOf("BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS").any { fields.containsKey(it) }) return null
            "weekly" -> if (fields["BYDAY"]?.let { it != dayNames[date.dayOfWeek.value % 7] } == true || listOf("BYMONTHDAY", "BYMONTH", "BYSETPOS").any { fields.containsKey(it) }) return null
            "monthly" -> {
                val byDay = fields["BYDAY"]
                if (byDay != null) {
                    if (fields.containsKey("BYMONTHDAY") || fields.containsKey("BYMONTH") || !matches(byDay, "(?:-1|[1-4])?(?:MO|TU|WE|TH|FR|SA|SU)")) return null
                    weekday = byDay.takeLast(2); val number = byDay.dropLast(2)
                    if (number.isNotEmpty()) { if (fields.containsKey("BYSETPOS")) return null; ordinal = integer(number) }
                    else if (fields["BYSETPOS"] in setOf("-1", "1", "2", "3", "4")) ordinal = integer(fields.getValue("BYSETPOS")) else return null
                } else if (fields.containsKey("BYSETPOS") || fields.containsKey("BYMONTH") || date.dayOfMonth > 28 || fields["BYMONTHDAY"]?.let { it != date.dayOfMonth.toString() } == true) return null
            }
            "yearly" -> if (fields.containsKey("BYDAY") || fields.containsKey("BYSETPOS") || fields["BYMONTH"]?.let { it != date.monthValue.toString() } == true || fields["BYMONTHDAY"]?.let { it != date.dayOfMonth.toString() } == true || date.monthValue == 2 && date.dayOfMonth == 29) return null
        }
        var until = ""
        fields["UNTIL"]?.let { value ->
            if ('T' in value && !value.endsWith("00") && !value.endsWith("00Z")) return null
            val ending = resolver.clock(Property("DTSTART" + (if (value.length == 8) ";VALUE=DATE" else "") + ":" + value))
            var last = java.time.Instant.ofEpochSecond(ending.instant).atZone(if (ending.dateOnly) ZoneOffset.UTC else resolver.display)
            if (!ending.dateOnly && resolver.time(start).isNotEmpty() && resolver.time(ending) < resolver.time(start)) last = last.minusDays(1)
            until = last.toLocalDate().toString()
        }
        return linkedMapOf<String, Any>("art" to type, "bis" to until).also {
            if (interval > 1) it["intervall"] = interval
            if (ordinal != null) { it["ordinal"] = ordinal!!; it["wochentag"] = weekday; if (fields.containsKey("BYSETPOS")) it["rruleForm"] = "bysetpos" }
        }
    }
    private fun rawProperties(component: Component): MutableList<String> {
        val retained = mutableSetOf("RRULE", "RDATE", "EXDATE", "EXRULE", "RECURRENCE-ID", "DURATION", "DTSTART", "DTEND", "DUE", "LOCATION", "URL", "ORGANIZER", "ATTENDEE", "ATTACH", "X-ALT-DESC", "TRANSP", "BEGIN", "END", "ACTION", "TRIGGER", "REPEAT")
        val generated = setOf("UID", "DTSTAMP", "LAST-MODIFIED", "SEQUENCE", "DTSTART", "DTEND", "DUE", "SUMMARY", "DESCRIPTION", "CATEGORIES", "CLASS", "STATUS", "PRIORITY", "PERCENT-COMPLETE", "X-MAGNOLIE-ERINNERUNG-AM-TAG", "X-MAGNOLIE-KOSTENSTELLE", "X-MAGNOLIE-KUNDE", "X-MAGNOLIE-ERINNERUNG-TAGE", "X-MAGNOLIE-STANDARDERINNERUNG", "X-MAGNOLIE-DATE", "X-MAGNOLIE-REIHENFOLGE", "X-MAGNOLIE-TASK-IDENTITY")
        if (component.property("RECURRENCE-ID") != null) retained.addAll(listOf("SUMMARY", "DESCRIPTION", "CATEGORIES", "CLASS", "STATUS", "PRIORITY"))
        var depth = 0; val result = mutableListOf<String>()
        for (line in component.lines.drop(1).dropLast(1)) {
            val property = Property(line)
            if (property.name == "BEGIN") depth++
            val parentLink = property.name == "RELATED-TO" && upper(property.parameters["RELTYPE"] ?: "") == "PARENT"
            if (!parentLink && (depth > 0 || property.name in retained || property.name !in generated || property.name == "STATUS" && upper(property.value) == "CANCELLED" || property.parameters.isNotEmpty())) result.add(line)
            if (property.name == "END") depth--
        }
        return result
    }
    private fun sourcePath(value: String) = value.replace('\\', '/').split('/').map {
        it.filter { c -> c.code >= 32 && c.code != 127 }.trim().replace(':', '_')
    }.filter { it.isNotEmpty() && it != "." && it != ".." }.joinToString("/")
    private fun foldedKey(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFD)
        .replace(Regex("\\p{M}+"), "").lowercase(Locale.ROOT).replace("ß", "ss").trim().split(Regex("\\s+")).joinToString(" ")
    private val anniversaryTypes = mapOf(
        "birthday" to listOf("Birthday", "Geburtstag"), "death-anniversary" to listOf("Death anniversary", "Todestag"),
        "wedding-anniversary" to listOf("Wedding anniversary", "Hochzeitstag"), "partnership-anniversary" to listOf("Partnership anniversary", "Partnerschaftstag"),
        "name-day" to listOf("Name day", "Namenstag"), "baptism" to listOf("Baptism", "Tauftag"), "first-communion" to listOf("First Communion", "Kommunion"),
        "confirmation" to listOf("Confirmation", "Konfirmation"), "catholic-confirmation" to listOf("Catholic confirmation", "Firmung"),
        "anniversary" to listOf("Anniversary", "Jubiläum"), "club-anniversary" to listOf("Club anniversary", "Vereinsjubiläum"),
        "work-anniversary" to listOf("Work anniversary", "Dienstjubiläum"), "founding-day" to listOf("Founding day", "Gründungstag"),
        "memorial-day" to listOf("Memorial day", "Gedenktag"), "other" to listOf("Other", "Sonstiges"))
    private fun anniversaryType(value: String): String = anniversaryTypes.entries.firstOrNull { foldedKey(it.key) == foldedKey(value) || it.value.any { label -> foldedKey(label) == foldedKey(value) } }?.key ?: ""
    private fun taskIdentity(text: String): JSONObject {
        // Android's JSONTokener accepts unquoted names and duplicate object keys.
        // Validate the small identity object with strict JSON tokens first.
        val token = "\"(?:[^\"\\\\\\x00-\\x1f]|\\\\[\"\\\\/bfnrt]|\\\\u[0-9a-fA-F]{4})*\""
        val number = "-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
        val field = Regex("\\s*($token)\\s*:\\s*($token|$number)\\s*")
        val input = text.trim(); requireImport(input.startsWith('{') && input.endsWith('}'), "Invalid source task identity.")
        val body = input.substring(1, input.lastIndex); var at = 0; val keys = mutableSetOf<String>()
        while (at < body.length) {
            val match = field.find(body, at)
            requireImport(match != null && match.range.first == at, "Invalid source task identity JSON.")
            val found = match!!; val key = JSONArray("[" + found.groupValues[1] + "]").getString(0)
            requireImport(keys.add(key), "Duplicate source task identity key.")
            at = found.range.last + 1
            if (at == body.length) break
            requireImport(body[at] == ',', "Invalid source task identity JSON."); at++
            requireImport(body.substring(at).isNotBlank(), "Trailing source task identity comma.")
        }
        val result = JSONObject(input)
        requireImport(keys == setOf("v", "source", "uid", "parent", "parentSource") && result.opt("v") is Number && (result.get("v") as Number).toDouble() == 1.0 &&
            listOf("source", "uid", "parent", "parentSource").all { result.opt(it) is String && '\u0000' !in result.getString(it) } && result.getString("uid").isNotEmpty(), "Invalid source task identity.")
        return result
    }
    private fun aliasMatches(actual: String, original: String, alias: String): Boolean = actual == original || actual == alias || actual.startsWith("$alias-") && matches(actual.removePrefix("$alias-"), "[1-9][0-9]*")
    private fun componentRecord(component: Component, complexUIDs: Set<String>, resolver: Resolver): Pair<String, MutableMap<String, Any>> {
        val wireUID = component.value("UID"); requireImport(wireUID.isNotEmpty(), "Calendar items require a UID; nothing was imported.")
        var baseUID = wireUID
        val taskIdentity = if (component.name == "VTODO") component.property("X-MAGNOLIE-TASK-IDENTITY")?.let { taskIdentity(unescape(it.value)) } else null
        if (taskIdentity != null) {
            val sourceUID = taskIdentity.getString("uid"); val source = taskIdentity.getString("source")
            requireImport(aliasMatches(wireUID, sourceUID, "urn:magnolie:task:" + hash(source + "\u0000" + sourceUID)), "Task identity does not match its calendar UID.")
            baseUID = sourceUID
        }
        val seriesUID = baseUID; val recurrence = component.property("RECURRENCE-ID")
        if (recurrence != null) {
            val parameters = recurrence.parameters.keys.sorted().joinToString(",", "{", "}") { JSONObject.quote(it) + ":" + JSONObject.quote(recurrence.parameters.getValue(it)) }
            val json = "[" + parameters + "," + JSONObject.quote(recurrence.value) + "]"
            baseUID += "-magnolie-instanz-" + hash(json).take(16)
        }
        var modified = 0L
        for (name in listOf("LAST-MODIFIED", "DTSTAMP")) {
            component.property(name)?.let { property ->
                val clock = resolver.clock(property); requireImport(!clock.dateOnly, "Invalid calendar modification timestamp.")
                modified = clock.instant * 1000
            }
            if (modified != 0L) break
        }
        val sequence = integer(component.value("SEQUENCE")); requireImport(sequence >= 0, "Invalid calendar sequence.")
        val rules = linkedMapOf<String, Map<String, String>>()
        for (property in component.properties.filter { it.name == "RRULE" || it.name == "EXRULE" }) {
            requireImport(!rules.containsKey(property.name), "Multiple source recurrence rules cannot be imported unambiguously.")
            rules[property.name] = ruleDictionary(property.value)
        }
        for (alarm in component.children.filter { it.name == "VALARM" }) requireImport(alarm.properties.count { it.name == "ACTION" } == 1 && alarm.properties.count { it.name == "TRIGGER" } == 1, "Imported alarm is incomplete or ambiguous.")
        fun reminder(name: String): Long { val n = integer(component.value(name)); return if (n in 1..7) n else 0 }
        fun color(): String { val value = component.value("X-MAGNOLIE-ACCENT-COLOR"); return if (matches(value, "#[0-9a-fA-F]{6}")) value.lowercase(Locale.ROOT) else "" }
        val raw = rawProperties(component); val title = component.value("SUMMARY")
        if (component.name == "VTODO") {
            requireImport(title.isNotEmpty(), "An imported task has no title.")
            val start = component.property("DTSTART")?.let(resolver::clock)
            var end = component.property("DUE")?.let(resolver::clock)
            component.property("DURATION")?.let { specification ->
                requireImport(start != null && end == null, "Ambiguous task duration."); end = resolver.duration(specification.value, start!!)
            }
            requireImport(start == null || end == null || start.instant <= end!!.instant, "Task end precedes start.")
            val priority = integer(component.value("PRIORITY")); requireImport(priority in 0..9, "Invalid task priority.")
            var parent = component.properties.firstOrNull { it.name == "RELATED-TO" && upper(it.parameters["RELTYPE"] ?: "") == "PARENT" }?.value?.let(::unescape) ?: ""
            var parentSource = ""
            if (taskIdentity != null) {
                val original = taskIdentity.getString("parent"); val source = taskIdentity.getString("parentSource")
                requireImport(parent == original || original.isNotEmpty() && aliasMatches(parent, original, "urn:magnolie:task:" + hash(source + "\u0000" + original)), "Task parent identity does not match RELATED-TO.")
                parent = original; parentSource = source
            }
            val order = integer(component.value("X-MAGNOLIE-REIHENFOLGE")); requireImport(order >= 0, "Invalid task ordering.")
            raw.removeAll { it.startsWith("X-MAGNOLIE-TASK-IDENTITY:") }
            val result = linkedMapOf<String, Any>("uid" to baseUID, "titel" to title, "faellig" to (end?.let(resolver::date) ?: ""), "faelligZeit" to (end?.let(resolver::time) ?: ""),
                "startDatum" to (start?.let(resolver::date) ?: ""), "startZeit" to (start?.let(resolver::time) ?: ""), "icsAnzeigeZeitzone" to resolver.displayName,
                "prio" to (if (priority in 1..3) 1 else if (priority >= 7) 3 else 2), "erledigt" to (upper(component.value("STATUS")) == "COMPLETED" || component.value("PERCENT-COMPLETE") == "100"),
                "notiz" to component.value("DESCRIPTION"), "kategorien" to component.value("CATEGORIES"), "akzentFarbe" to color(), "erinnern" to (component.value("X-MAGNOLIE-ERINNERUNG-AM-TAG") == "1"),
                "individuelleErinnerungTage" to reminder("X-MAGNOLIE-ERINNERUNG-TAGE"), "icsSerienUid" to (if (recurrence == null) "" else seriesUID), "elternUid" to parent, "icsElternUid" to parent,
                "icsElternQuelleId" to parentSource, "reihenfolge" to order, "geaendert" to modified, "icsRoundtrip" to raw)
            if (taskIdentity != null) result["icsQuelleId"] = taskIdentity.getString("source")
            return "aufgaben" to result
        }
        requireImport(component.name == "VEVENT", "Unsupported imported component.")
        val startProperty = component.property("DTSTART") ?: recurrence?.takeIf { upper(component.value("STATUS")) == "CANCELLED" } ?: throw ImportException("An imported event has no start.")
        val start = resolver.clock(startProperty); var end = component.property("DTEND")?.let(resolver::clock)
        component.property("DURATION")?.let {
            requireImport(end == null, "An event has both DTEND and DURATION."); end = resolver.duration(it.value, start)
        }
        requireImport(end == null || end!!.instant >= start.instant && end!!.dateOnly == start.dateOnly, "Invalid event time range.")
        val date = resolver.date(start); val time = resolver.time(start); var endDate = ""; var endTime = ""
        end?.let { ending ->
            val exclusive = ending.instant - if (start.dateOnly) 86400 else 0
            val projected = java.time.Instant.ofEpochSecond(exclusive).atZone(if (start.dateOnly) ZoneOffset.UTC else resolver.display).toLocalDate().toString()
            if (projected > date) endDate = projected
            if (!start.dateOnly && (resolver.date(ending) > date || resolver.time(ending) != time)) endTime = resolver.time(ending)
        }
        val recurrenceNames = component.properties.filter { it.name in setOf("RRULE", "RDATE", "EXDATE", "EXRULE", "RECURRENCE-ID") }.map { it.name }
        var complex = seriesUID in complexUIDs || recurrenceNames.any { it in setOf("EXDATE", "EXRULE", "RECURRENCE-ID") }
        val sourceName = if (start.source == absoluteUTC) "UTC" else start.source
        if (rules.containsKey("RRULE") && time.isNotEmpty() && sourceName.isNotEmpty() && sourceName != resolver.displayName) complex = true
        if (rules.containsKey("RRULE") && component.property("DURATION") != null) complex = true
        if (rules.containsKey("RRULE") && time.isNotEmpty() && (endTime.isEmpty() || start.wall.second != 0 || end?.wall?.second?.let { it != 0 } == true)) complex = true
        val additions = mutableListOf<String>(); val additionRecords = mutableListOf<Map<String, String>>()
        for (property in component.properties.filter { it.name in setOf("RDATE", "EXDATE", "RECURRENCE-ID") }) {
            for (value in property.value.split(',')) {
                if (upper(property.parameters["VALUE"] ?: "") == "PERIOD") {
                    requireImport(property.name == "RDATE", "Only RDATE supports PERIOD values.")
                    val pair = value.split('/', limit = 2); requireImport(pair.size == 2, "Invalid recurrence period.")
                    val header = Property(property.renamed("DTSTART", setOf("VALUE"))).header
                    val first = resolver.clock(Property("$header:" + pair[0]))
                    val finish = if (pair[1].startsWith("P") || pair[1].startsWith("+P")) resolver.duration(pair[1], first) else resolver.clock(Property("$header:" + pair[1]))
                    requireImport(finish.instant > first.instant, "Recurrence period has no positive duration."); complex = true; continue
                }
                val clock = resolver.clock(Property(property.header + ":" + value))
                requireImport(clock.dateOnly == start.dateOnly, "Recurrence dates do not match DTSTART's value type.")
                if (property.name == "RDATE" && !complex) {
                    val rd = resolver.date(clock); val rt = resolver.time(clock)
                    if (rd < date || rd == date && rt < time) { complex = true; additions.clear(); additionRecords.clear(); continue }
                    if (rd == date && rt == time) continue
                    additions.add(rd); val projected = mapOf("datum" to rd, "zeit" to rt); if (projected !in additionRecords) additionRecords.add(projected)
                }
            }
        }
        var repetition: Map<String, Any>? = if (!complex) rules["RRULE"]?.let { simpleRule(it, start, resolver) } else null
        if (!complex && !rules.containsKey("RRULE") && additions.isNotEmpty()) repetition = mapOf("art" to "custom", "bis" to "", "daten" to additions.distinct().sorted())
        val explicit = anniversaryType(component.value("X-MAGNOLIE-TYPE-ID"))
        val legacy = component.value("X-MAGNOLIE-TYP").ifEmpty { component.value("X-MAGNOLIE-JAHRESTAG-TYP") }
        val type = explicit.ifEmpty { anniversaryType(legacy).ifEmpty { legacy } }
        val yearly = !rules.containsKey("RRULE") || !complex && recurrenceNames == listOf("RRULE") && upper(component.value("RRULE")) in setOf("FREQ=YEARLY", "FREQ=YEARLY;INTERVAL=1") || repetition?.get("art") == "yearly" && repetition["bis"] == ""
        if (type.isNotEmpty() && yearly && endDate.isEmpty() && (time.isEmpty() || time == "00:00" && endTime == "23:59")) {
            var sourceDate = date; val yearless = component.value("X-MAGNOLIE-DATE")
            if (yearless.isNotEmpty()) {
                requireImport(matches(yearless, "--[0-9]{2}-[0-9]{2}") && date.takeLast(5) == yearless.takeLast(5), "Anniversary date extension contradicts DTSTART.")
                naive("2000" + yearless.replace("-", "")); sourceDate = yearless
            }
            return "jahrestage" to linkedMapOf("uid" to baseUID, "name" to title, "datum" to sourceDate, "typ" to type, "icsSerienUid" to seriesUID, "notiz" to component.value("DESCRIPTION"), "icsRoundtrip" to raw, "geaendert" to modified)
        }
        val isComplex = complex || rules.containsKey("RRULE") && repetition == null
        return "termine" to linkedMapOf("uid" to baseUID, "titel" to title.ifEmpty { "Untitled appointment" }, "datum" to date, "endDatum" to endDate, "zeit" to time, "endZeit" to endTime,
            "icsAnzeigeZeitzone" to resolver.displayName, "notiz" to component.value("DESCRIPTION"), "kategorien" to component.value("CATEGORIES"), "akzentFarbe" to color(),
            "vertraulich" to (upper(component.value("CLASS")) in setOf("CONFIDENTIAL", "PRIVATE")), "vorlaeufig" to (upper(component.value("STATUS")) == "TENTATIVE"),
            "kostenstelle" to component.value("X-MAGNOLIE-KOSTENSTELLE"), "kunde" to component.value("X-MAGNOLIE-KUNDE"), "individuelleErinnerungTage" to reminder("X-MAGNOLIE-ERINNERUNG-TAGE"),
            "standardErinnerung" to (component.value("X-MAGNOLIE-STANDARDERINNERUNG") != "0"), "wiederholung" to (repetition ?: mapOf("art" to "none", "bis" to "")), "icsKomplex" to isComplex,
            "icsSerienUid" to (if (isComplex) seriesUID else ""), "icsZusatzDaten" to additions.distinct().sorted(), "icsZusatzTermine" to additionRecords, "icsEndeFehlt" to (end == null),
            "icsNullDauer" to (end?.instant == start.instant), "icsRoundtrip" to raw, "icsSequence" to sequence, "icsAenderungszeitFehlt" to (component.property("LAST-MODIFIED") == null), "geaendert" to modified)
    }

    @JvmOverloads
    fun decode(bytes: ByteArray, displayTimeZone: String = "system", sourceName: String = "", sourceId: String = "",
               checkCancelled: () -> Unit = { if (Thread.currentThread().isInterrupted) throw CancellationException("Calendar import cancelled.") }): Result {
        checkCancelled()
        requireImport(bytes.isNotEmpty() && bytes.size <= maximumBytes, "Calendar import requires a UTF-8 file no larger than 32 MiB.")
        val text = try { Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString() }
                   catch (_: java.nio.charset.CharacterCodingException) { throw ImportException("Calendar import requires valid UTF-8.") }
        val roots = parse(unfold(text.removePrefix("\uFEFF"), checkCancelled), checkCancelled)
        val wrapper = roots.singleOrNull()?.takeIf { it.name == "VCALENDAR" }
        val components = wrapper?.children ?: roots
        val items = components.filter { it.name in setOf("VEVENT", "VTODO") }
        requireImport(items.isNotEmpty() && items.size <= maximumRecords, "Calendar contains no supported items or too many items.")
        val display = if (displayTimeZone.isEmpty() || displayTimeZone == "system") ZoneId.systemDefault() else knownZone(displayTimeZone)
        val displayName = if (displayTimeZone.isEmpty() || displayTimeZone == "system") display.id else displayTimeZone
        val zoneBlocks = mutableListOf<List<String>>(); val zoneSources = mutableMapOf<String, List<String>>(); val zones = mutableMapOf<String, EmbeddedZone>()
        for (component in components.filter { it.name == "VTIMEZONE" }) {
            checkCancelled()
            val names = component.properties.filter { it.name == "TZID" }
            requireImport(names.size == 1 && names[0].value.isNotEmpty(), "Source time zone has no unique TZID.")
            val name = names[0].value; val previous = zoneSources[name]
            if (previous != null) { requireImport(previous == component.lines, "Conflicting source definitions share a TZID."); continue }
            zones[name] = EmbeddedZone(component, checkCancelled); zoneSources[name] = component.lines; zoneBlocks.add(component.lines)
        }
        val resolver = Resolver(display, displayName, zones)
        val complexUIDs = items.filter { it.name == "VEVENT" && it.property("RECURRENCE-ID") != null }.map { it.value("UID") }.toSet()
        val calendarName = wrapper?.value("X-WR-CALNAME")?.trim() ?: ""
        val fallback = sourcePath(sourceName).ifEmpty { "Calendar" }; val label = calendarName.ifEmpty { fallback }
        val qualified = sourceName.isNotEmpty() || sourceId.isNotEmpty() || calendarName.isNotEmpty()
        val stableSource = sourceId.ifEmpty { if (sourceName.isEmpty()) "calendar" else fallback }
        val source = "ics:" + hash(stableSource + "\n" + calendarName)
        val collections = linkedMapOf("termine" to mutableListOf<MutableMap<String, Any>>(), "aufgaben" to mutableListOf(), "jahrestage" to mutableListOf())
        val identities = mutableSetOf<String>(); var projected = 0L
        val zoneBytes = zoneBlocks.sumOf { block -> block.sumOf { it.toByteArray(Charsets.UTF_8).size.toLong() + 2 } }
        for (component in items) {
            checkCancelled()
            val itemBytes = component.lines.sumOf { it.toByteArray(Charsets.UTF_8).size.toLong() + 2 }
            projected += (itemBytes + zoneBytes) * 6 + 8192
            requireImport(projected <= maximumProjectedBytes, "Projected calendar data exceeds the bounded import size; nothing was imported.")
            val (collection, record) = componentRecord(component, complexUIDs, resolver)
            requireImport(identities.add(collection + "\u0000" + record.getValue("uid")), "Duplicate calendar item identity; nothing was imported.")
            if (qualified) { record["icsQuelleName"] = label; if (!record.containsKey("icsQuelleId")) record["icsQuelleId"] = source }
            if (collection == "aufgaben" && record["icsElternQuelleId"] == "" && component.property("X-MAGNOLIE-TASK-IDENTITY") == null) record["icsElternQuelleId"] = record["icsQuelleId"] ?: ""
            if (zoneBlocks.isNotEmpty()) record["icsTimezones"] = zoneBlocks
            collections.getValue(collection).add(record)
        }
        for (collection in listOf("termine", "aufgaben")) {
            val records = collections.getValue(collection); val exclusions = mutableMapOf<String, MutableList<String>>(); val ranges = mutableMapOf<String, MutableList<List<String>>>()
            fun key(record: Map<String, Any>) = (record["icsQuelleId"] as? String ?: "") + "\u0000" + ((record["icsSerienUid"] as? String)?.takeIf { it.isNotEmpty() } ?: record.getValue("uid"))
            for (record in records) {
                checkCancelled()
                @Suppress("UNCHECKED_CAST") val raw = record["icsRoundtrip"] as List<String>
                raw.firstOrNull { Property(it).name == "RECURRENCE-ID" }?.let { line ->
                    val property = Property(line); val key = key(record)
                    exclusions.getOrPut(key) { mutableListOf() }.add(property.renamed("EXDATE", setOf("RANGE")))
                    if (upper(property.parameters["RANGE"] ?: "") == "THISANDFUTURE") ranges.getOrPut(key) { mutableListOf() }.add(raw)
                }
            }
            for (record in records) {
                checkCancelled()
                @Suppress("UNCHECKED_CAST") val raw = record["icsRoundtrip"] as MutableList<String>
                if (raw.none { Property(it).name == "RECURRENCE-ID" }) {
                    val key = key(record)
                    exclusions[key]?.let { lines ->
                        for (line in lines) if (line !in raw) raw.add(line)
                        record["icsRangeOverrides"] = ranges[key] ?: emptyList<List<String>>()
                    }
                }
            }
        }
        checkCancelled()
        val result = Result(collections.getValue("termine").map(::JSONObject), collections.getValue("aufgaben").map(::JSONObject), collections.getValue("jahrestage").map(::JSONObject), wrapper?.properties?.map { it.line } ?: emptyList(), hash(bytes))
        requireImport(result.document.toString().toByteArray(Charsets.UTF_8).size <= maximumProjectedBytes, "Calendar projection exceeds the bounded import size.")
        checkCancelled()
        return result
    }
}
