package io.gitlab.maik3531.magnolietabletbeta

import java.net.URI
import java.net.URLEncoder
import java.util.Locale
import java.util.concurrent.CancellationException
import org.json.JSONArray
import org.json.JSONObject

class HolidayException(val code: String) : Exception(code)
class HolidayService(private val transport: BoundedHttpTransport, private val monotonicNanos: () -> Long = System::nanoTime) {
    data class Region(val code: String, val name: String)
    data class Query(val country: String, val regions: List<Region>, val years: List<Int>, val includeSchool: Boolean, val language: String = "EN", val requestId: String? = null)
    data class Entry(val start: String, val end: String, val name: String, val kind: String, val country: String, val nationwide: Boolean, val regions: List<String>, val selectedRegions: List<String>, val regionNames: List<String>, val regionLabel: String)
    data class Coverage(val country: String, val region: String, val kind: String, val start: String, val end: String)
    data class Result(val entries: List<Entry>, val years: List<Int>, val requestId: String?, val report: String, val coverage: List<Coverage> = emptyList())
    private data class Key(val start: String, val end: String, val name: String, val kind: String)
    private class Group(val start: String, val end: String, val name: String, val kind: String) {
        var nationwide = false
        val regions = sortedSetOf<String>()
        val selected = sortedSetOf<String>()
        val names = sortedSetOf<String>()
    }

// INSERT EXACT FETCH METHOD HERE

    companion object {
        private val REGION = Regex("^[A-Z0-9-]{1,64}$")
        private val AUSTRIAN_PROVIDER_REGIONS = mapOf("AT-1" to "AT-BL", "AT-2" to "AT-KÄ",
            "AT-3" to "AT-NÖ", "AT-4" to "AT-OÖ", "AT-5" to "AT-SB", "AT-6" to "AT-SM",
            "AT-7" to "AT-TI", "AT-8" to "AT-VA", "AT-9" to "AT-WI")
        private val AUSTRIAN_ISO_REGIONS = AUSTRIAN_PROVIDER_REGIONS.entries.associate { (iso, provider) -> provider to iso }
        private const val RESPONSE_BYTES = 2 * 1024 * 1024
        private const val TOTAL_BYTES = 16 * 1024 * 1024
        private const val TOTAL_TIMEOUT_MILLIS = 90_000L
        private fun invalidQuery(): Nothing = throw HolidayException("holiday_invalid_query")
        private fun invalidResponse(): Nothing = throw HolidayException("holiday_invalid_response")
        private fun validDate(value: String): Boolean = try { java.time.LocalDate.parse(value); true } catch (_: Exception) { false }
        private fun normalizedName(value: String): String = value.lowercase(Locale.ROOT)
        private fun title(value: Any?, language: String): String = value as? String ?: invalidResponse()
        private fun parse(data: ByteArray, checkpoint: () -> Unit): JSONArray { checkpoint(); return Fixtures.responses.getValue(data.decodeToString()) }
        private fun report(entries: List<Entry>, query: Query): String = ""
    }
}
