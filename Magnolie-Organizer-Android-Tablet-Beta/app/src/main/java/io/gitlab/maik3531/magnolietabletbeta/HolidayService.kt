package io.gitlab.maik3531.magnolietabletbeta

import java.net.URI
import java.net.URLEncoder
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.text.Normalizer
import org.threeten.bp.LocalDate
import java.util.Locale
import java.util.concurrent.CancellationException
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener

/** Safe codes only; provider payloads and network exception messages never reach the UI. */
class HolidayException(val code: String) : Exception(code)

/** Public data only, fixed HTTPS origin, no credentials or persistent/partial cache.
 * fetch blocks: use the dedicated network executor, never Android's main/store thread.
 */
class HolidayService(
    private val transport: BoundedHttpTransport = OkHttpBoundedTransport(),
    private val monotonicNanos: () -> Long = System::nanoTime
) {
    data class Region(val code: String, val name: String)

    class Query(
        country: String, regions: List<Region> = emptyList(), years: List<Int>, includeSchool: Boolean,
        regionRequired: Boolean = false, language: String = "EN", val requestId: String? = null
    ) {
        val country: String
        val regions: List<Region>
        val years: List<Int>
        val includeSchool: Boolean
        val language: String
        init {
            this.country = country.trim().uppercase(Locale.ROOT)
            if (country.length > 32 || !COUNTRY.matches(this.country) || years.isEmpty() || years.size > 256 ||
                years.toSet().size > 3 || years.any { it !in 1..9999 } || regions.size > 26 ||
                language.length > 128 || requestId != null && (requestId.isEmpty() || requestId.length > 256 || requestId.any { it < ' ' })) invalidQuery()
            this.regions = regions.map {
                val code = it.code.trim().uppercase(Locale.ROOT)
                if (it.code.length > 128 || !REGION.matches(code) || it.name.length > 256 || it.name.any { c -> c < ' ' }) invalidQuery()
                Region(code, it.name.trim())
            }.distinctBy { it.code }.toList()
            this.years = years.distinct().sorted()
            this.includeSchool = includeSchool && (!regionRequired || this.regions.isNotEmpty())
            this.language = if (language.lowercase(Locale.ROOT).startsWith("de") || language.lowercase(Locale.ROOT) == "system") "DE" else "EN"
        }

        companion object {
            /** The bridge supplies the current saved UI language, never a remote URL. */
            fun fromMessage(message: JSONObject, language: String = "EN"): Query {
                val allowed = setOf("cmd", "land", "region", "regionen", "jahre", "ferien", "regionErforderlich", "requestId", "session", "revision")
                if (message.keys().asSequence().any { it !in allowed } || message.opt("cmd") != "feiertage") invalidQuery()
                for (key in listOf("session", "revision")) if (message.has(key) && message.opt(key) !is String) invalidQuery()
                fun string(key: String, default: String? = null): String = when (val value = message.opt(key)) {
                    null, JSONObject.NULL -> default ?: invalidQuery()
                    is String -> value
                    else -> invalidQuery()
                }
                fun boolean(key: String, default: Boolean): Boolean = when (val value = message.opt(key)) {
                    null -> default
                    is Boolean -> value
                    else -> invalidQuery()
                }
                val country = string("land")
                val selected = string("region", "")
                val rawRegions = when (val raw = message.opt("regionen")) {
                    null -> JSONArray()
                    is JSONArray -> raw
                    else -> invalidQuery()
                }
                if (rawRegions.length() > 26) invalidQuery()
                val regions = (0 until rawRegions.length()).map { index ->
                    when (val raw = rawRegions.get(index)) {
                        is JSONObject -> {
                            if (raw.keys().asSequence().any { it !in setOf("code", "name") }) invalidQuery()
                            Region(raw.opt("code") as? String ?: invalidQuery(), raw.opt("name") as? String ?: invalidQuery())
                        }
                        is JSONArray -> {
                            if (raw.length() != 2) invalidQuery()
                            Region(raw.opt(0) as? String ?: invalidQuery(), raw.opt(1) as? String ?: invalidQuery())
                        }
                        else -> invalidQuery()
                    }
                }
                val rawYears = message.opt("jahre") as? JSONArray ?: invalidQuery()
                if (rawYears.length() !in 1..256) invalidQuery()
                val years = (0 until rawYears.length()).map { index ->
                    // JSON booleans, numeric strings, fractions and overflow must not become years.
                    val raw = rawYears.get(index)
                    if (raw !is Int && raw !is Long) invalidQuery()
                    val number = (raw as Number).toLong()
                    if (number !in 1..9999) invalidQuery()
                    number.toInt()
                }
                val requestId = when (val raw = message.opt("requestId")) {
                    null, JSONObject.NULL -> null
                    is String -> raw
                    else -> invalidQuery()
                }
                return Query(country, if (selected.isNotBlank()) listOf(Region(selected, "")) else regions,
                    years, boolean("ferien", true), boolean("regionErforderlich", false), language, requestId)
            }
        }
    }

    data class Entry(
        val start: String, val end: String, val name: String, val kind: String, val country: String,
        val nationwide: Boolean, val regions: List<String>, val selectedRegions: List<String>,
        val regionNames: List<String>, val regionLabel: String
    ) {
        /** OpenHolidays endDate is inclusive; do not add/subtract a day. */
        fun organizerValue(): JSONObject = JSONObject().put("von", start).put("bis", end).put("name", name)
            .put("art", kind).put("country", country).put("nationwide", nationwide)
            .put("regions", JSONArray(regions)).put("region", selectedRegions.joinToString(","))
            .put("regionName", regionLabel)
    }

    data class Result(val entries: List<Entry>, val years: List<Int>, val requestId: String?, val report: String) {
        fun callbackValue(): JSONObject = JSONObject().put("feiertage", JSONArray(entries.map { it.organizerValue() }))
            .put("jahre", JSONArray(years)).put("bericht", report).also { if (requestId != null) it.put("requestId", requestId) }
    }

    private data class Key(val start: String, val end: String, val name: String, val kind: String)
    private class Group(val start: String, val end: String, val name: String, val kind: String) {
        var nationwide = false
        val regions = sortedSetOf<String>()
        val selected = sortedSetOf<String>()
        val names = sortedSetOf<String>()
    }

    fun fetch(query: Query, cancellation: DavCancellation = DavCancellation()): Result {
        val started = monotonicNanos()
        fun remainingMillis(): Long {
            cancellation.check()
            val elapsed = (monotonicNanos() - started) / 1_000_000
            if (elapsed < 0 || elapsed >= TOTAL_TIMEOUT_MILLIS) throw HolidayException("holiday_timeout")
            return TOTAL_TIMEOUT_MILLIS - elapsed
        }
        val selections: List<Region?> = if (query.regions.isEmpty()) listOf(null) else query.regions
        val kinds = if (query.includeSchool) listOf("PublicHolidays" to "public-holiday", "SchoolHolidays" to "school-holiday")
            else listOf("PublicHolidays" to "public-holiday")
        val groups = linkedMapOf<Key, Group>()
        var receivedBytes = 0
        for (year in query.years) for ((endpoint, kind) in kinds) for (region in selections) {
            val remaining = remainingMillis()
            val fields = linkedMapOf("countryIsoCode" to query.country, "languageIsoCode" to query.language,
                "validFrom" to "%04d-01-01".format(Locale.ROOT, year), "validTo" to "%04d-12-31".format(Locale.ROOT, year))
            if (region != null) fields["subdivisionCode"] = region.code
            val uri = URI("https://openholidaysapi.org/$endpoint?" + fields.entries.joinToString("&") {
                URLEncoder.encode(it.key, "UTF-8") + "=" + URLEncoder.encode(it.value, "UTF-8")
            })
            val response = try {
                transport.send(BoundedHttpRequest(uri, headers = mapOf("Accept" to "application/json",
                    "User-Agent" to "Magnolie-Organizer-Android-Tablet/2.0.30"),
                    timeoutMillis = minOf(20_000, remaining), maxResponseBytes = RESPONSE_BYTES), cancellation)
            } catch (error: CancellationException) { throw error }
              catch (error: Exception) {
                  cancellation.check()
                  throw HolidayException(if (error is DavException && error.code == "timeout") "holiday_timeout" else "holiday_transport_error")
              }
            remainingMillis()
            if (response.status != 200) throw HolidayException("holiday_http_error")
            receivedBytes += response.body.size
            if (response.body.size > RESPONSE_BYTES || receivedBytes > TOTAL_BYTES) throw HolidayException("holiday_response_too_large")
            val rows = parse(response.body) { remainingMillis() }
            if (rows.length() > 10_000) throw HolidayException("holiday_response_too_large")
            for (index in 0 until rows.length()) {
                remainingMillis()
                val row = rows.opt(index) as? JSONObject ?: invalidResponse()
                val start = (row.opt("startDate") as? String ?: invalidResponse()).trim().take(10)
                val end = when (val raw = row.opt("endDate")) {
                    null, JSONObject.NULL -> start
                    is String -> raw.trim().take(10).ifEmpty { start }
                    else -> invalidResponse()
                }
                val name = title(row.opt("name"), query.language)
                if (!validDate(start) || !validDate(end) || end < start || name.isEmpty() || name.length > 1024) invalidResponse()
                val key = Key(start, end, normalizedName(name), kind)
                val group = groups.getOrPut(key) { Group(start, end, name, kind) }
                val nationwide = row.opt("nationwide") == true
                val scopes = sortedSetOf<String>()
                when (val subdivisions = row.opt("subdivisions")) {
                    null, JSONObject.NULL -> Unit
                    is JSONArray -> {
                        if (subdivisions.length() > 256) invalidResponse()
                        for (i in 0 until subdivisions.length()) {
                            remainingMillis()
                            val raw = subdivisions.opt(i) as? JSONObject ?: invalidResponse()
                            val code = (raw.opt("code") as? String ?: invalidResponse()).trim().uppercase(Locale.ROOT)
                            if (!REGION.matches(code)) invalidResponse()
                            scopes.add(code)
                        }
                    }
                    else -> invalidResponse()
                }
                if (region != null) {
                    group.selected.add(region.code)
                    if (region.name.isNotEmpty()) group.names.add(region.name)
                    if (!nationwide && scopes.isEmpty()) scopes.add(region.code)
                }
                group.nationwide = group.nationwide || nationwide
                group.regions.addAll(scopes)
                if (groups.size > 20_000) throw HolidayException("holiday_response_too_large")
            }
        }
        val allNames = query.regions.map { it.name }.filter { it.isNotEmpty() }.toSet()
        val entries = groups.values.map { group ->
            remainingMillis()
            val label = when {
                query.regions.size <= 1 || group.names.isEmpty() -> group.names.firstOrNull().orEmpty()
                group.names == allNames -> if (query.language == "DE") {
                    if (query.country == "CH") "alle Kantone" else "alle Bundesländer"
                } else if (query.country == "CH") "all cantons" else "all states"
                group.names.size > allNames.size / 2 -> (if (query.language == "DE") "alle außer " else "all except ") +
                    allNames.subtract(group.names).sorted().joinToString(", ")
                else -> group.names.joinToString(", ")
            }
            Entry(group.start, group.end, group.name + if (query.regions.size > 1 && label.isNotEmpty()) " ($label)" else "",
                group.kind, query.country, group.nationwide, group.regions.toList(), group.selected.toList(), group.names.toList(), label)
        }.sortedWith(compareBy({ it.start }, { it.name }, { it.kind }))
        remainingMillis()
        return Result(entries, query.years, query.requestId, report(entries, query))
    }

    companion object {
        private val COUNTRY = Regex("^[A-Z]{2}$")
        private val REGION = Regex("^[A-Z0-9-]{1,64}$")
        private val DATE = Regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
        private const val RESPONSE_BYTES = 2 * 1024 * 1024
        private const val TOTAL_BYTES = 16 * 1024 * 1024
        private const val TOTAL_TIMEOUT_MILLIS = 90_000L
        private fun invalidQuery(): Nothing = throw HolidayException("holiday_invalid_query")
        private fun invalidResponse(): Nothing = throw HolidayException("holiday_invalid_response")
        private fun validDate(value: String): Boolean = DATE.matches(value) && !value.startsWith("0000") &&
            try { LocalDate.parse(value); true } catch (_: Exception) { false }
        private fun normalizedName(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFKD)
            .replace("ß", "ss").replace(Regex("\\p{M}"), "").lowercase(Locale.ROOT).trim().replace(Regex("\\s+"), " ")
        private fun title(value: Any?, language: String): String {
            if (value is String) return value.trim()
            val names = value as? JSONArray ?: invalidResponse()
            if (names.length() > 256) invalidResponse()
            var fallback = ""
            for (i in 0 until names.length()) {
                val item = names.opt(i) as? JSONObject ?: invalidResponse()
                val text = (item.opt("text") as? String ?: invalidResponse()).trim()
                if (text.isEmpty()) continue
                if (fallback.isEmpty()) fallback = text
                if ((item.opt("language") as? String)?.uppercase(Locale.ROOT) == language) return text
            }
            return fallback
        }
        private fun parse(data: ByteArray, checkpoint: () -> Unit): JSONArray {
            try {
                checkpoint()
                val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data)).toString()
                // Bound JSON recursion before Android's recursive JSONTokener sees provider input.
                var depth = 0; var quoted = false; var escaped = false
                for ((index, char) in text.withIndex()) {
                    if (index % 4096 == 0) checkpoint()
                    if (quoted) {
                        if (escaped) escaped = false else if (char == '\\') escaped = true else if (char == '"') quoted = false
                    } else when (char) {
                        '"' -> quoted = true
                        '{', '[' -> { depth++; if (depth > 32) invalidResponse() }
                        '}', ']' -> { depth--; if (depth < 0) invalidResponse() }
                    }
                }
                if (quoted || depth != 0 || text.trimStart().firstOrNull() !in listOf('[', '{')) invalidResponse()
                val tokener = JSONTokener(text)
                val document = tokener.nextValue()
                checkpoint()
                if (tokener.nextClean() != '\u0000') invalidResponse()
                return when (document) {
                    is JSONArray -> document
                    is JSONObject -> document.opt("data") as? JSONArray ?: invalidResponse()
                    else -> invalidResponse()
                }
            } catch (error: CancellationException) { throw error }
              catch (error: HolidayException) { throw error }
              catch (_: Exception) { invalidResponse() }
        }
        private fun report(entries: List<Entry>, query: Query): String {
            if (entries.isEmpty()) return if (query.language == "DE") "Der Dienst hat für diese Auswahl keine Einträge geliefert."
                else "The service returned no entries for this selection."
            val public = entries.count { it.kind == "public-holiday" }
            val school = entries.count { it.kind == "school-holiday" }
            val parts = mutableListOf<String>()
            if (public > 0) parts.add(if (query.language == "DE") "$public Feiertag${if (public == 1) "" else "e"}"
                else "$public public holiday${if (public == 1) "" else "s"}")
            if (school > 0) parts.add(if (query.language == "DE") "$school Ferienabschnitt${if (school == 1) "" else "e"}"
                else "$school holiday period${if (school == 1) "" else "s"}")
            return (if (query.language == "DE") "Abgerufen: " else "Retrieved: ") + parts.joinToString(", ") +
                " ${if (query.language == "DE") "für" else "for"} ${query.years.joinToString(", ")}."
        }
    }
}
