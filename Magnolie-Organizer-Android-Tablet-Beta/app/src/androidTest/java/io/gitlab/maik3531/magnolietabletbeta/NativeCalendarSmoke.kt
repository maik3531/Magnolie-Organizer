package io.gitlab.maik3531.magnolietabletbeta

import android.content.Context
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Production calendar codecs on Android's actual org.json / java.time runtime.
 * Runs on the instrumentation worker, with public synthetic assets only. This
 * does not start an Activity, expand event occurrences, write a profile or sync. */
internal object NativeCalendarSmoke {
    private const val ASSET = "calendar-native-v2.0.30-oracle.json"
    private const val SHA256 = "a195c4ff916950757db9fcc641058b1035a829f549021c077aa1d1f636d28111"
    private val ignored = setOf("geaendert", "icsSequence", "icsAenderungszeitFehlt", "icsQuelleId", "icsQuelleName", "icsTimezones", "icsRoundtrip", "icsAnzeigeZeitzone")
    private val stamp = DateTimeFormatter.ofPattern("uuuuMMdd'T'HHmmss", Locale.ROOT)
    private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    private fun rows(array: JSONArray) = (0 until array.length()).map { array.getJSONObject(it) }
    private fun strings(array: JSONArray) = (0 until array.length()).map { array.getString(it) }
    private fun semantic(value: Any?): Any? = when (value) {
        null, JSONObject.NULL -> null
        is JSONObject -> value.keys().asSequence().toList().sorted().associateWith { semantic(value.get(it)) }
        is JSONArray -> (0 until value.length()).map { semantic(value.get(it)) }
        is Number -> value.toDouble()
        else -> value
    }
    private fun stable(record: JSONObject) = semantic(JSONObject(record.toString()).also { copy -> ignored.forEach { copy.remove(it) } })
    private fun unfold(text: String) = text.replace("\r\n ", "").replace("\r\n\t", "").split("\r\n")
    private fun compare(expected: JSONArray, actual: JSONArray) {
        check(expected.length() == actual.length()) { "Native calendar record count differs from published oracle" }
        for (index in 0 until expected.length()) check(stable(expected.getJSONObject(index)) == stable(actual.getJSONObject(index))) {
            "Native calendar semantic fields differ from published oracle at record $index"
        }
    }
    private fun rejectExport(action: () -> Unit) {
        val rejected = try { action(); false } catch (_: ICalendarExport.ExportException) { true }
        check(rejected) { "Native calendar export did not reject unsafe source data" }
    }
    private fun event() = JSONObject().put("uid", "native-calendar-event").put("titel", "Synthetic appointment")
        .put("datum", "2026-03-28").put("zeit", "10:00").put("endZeit", "11:00").put("icsAnzeigeZeitzone", "UTC")

    fun run(instrumentationContext: Context): JSONObject {
        check(Looper.myLooper() != Looper.getMainLooper()) { "Native calendar checks require the instrumentation worker" }
        check(android.os.Build.FINGERPRINT.contains("generic") || android.os.Build.MODEL.contains("sdk")) { "Disposable emulator required" }
        // Context is Instrumentation.context, never targetContext: this asset is
        // part of the test APK and must not enter the application's shipped assets.
        val bytes = instrumentationContext.assets.open(ASSET).use { it.readBytes() }
        check(bytes.size <= 1024 * 1024 && hash(bytes) == SHA256) { "Native calendar oracle asset checksum mismatch" }
        val golden = JSONObject(bytes.toString(Charsets.UTF_8))
        check(golden.getString("canonicalTag") == "v2.0.30" && golden.getString("canonicalCommit") == "067c38934b539943d8e1720abafd8a80b401d797") {
            "Unexpected published calendar oracle revision"
        }
        val cases = golden.getJSONArray("cases"); check(cases.length() == 8)
        val groups = mapOf("ics-termine" to "termine", "ics-aufgaben" to "aufgaben", "ics-jahrestage" to "jahrestage")
        var importedRecords = 0; var exportedRecords = 0; var rawProperties = 0; var sourceZones = 0
        for (index in 0 until cases.length()) {
            check(!Thread.currentThread().isInterrupted) { "Native calendar proof cancelled" }
            val case = cases.getJSONObject(index)
            val source = case.getString("importSource").toByteArray(Charsets.UTF_8)
            val imported = ICalendarImport.decode(source, "UTC").document
            val expected = case.getJSONObject("importExpected")
            val metadata = imported.getJSONObject("icsImportMetadata")
            check(metadata.getInt("version") == 1 && metadata.getString("sourceSHA256") == hash(source)) { "Native calendar source binding mismatch" }
            check("VERSION:2.0" in strings(metadata.getJSONArray("calendarProperties"))) { "Native calendar wrapper metadata missing" }
            for ((kind, group) in groups) {
                val original = expected.getJSONArray(group); val actual = imported.getJSONArray(group)
                compare(original, actual); importedRecords += actual.length()
                for (row in 0 until original.length()) {
                    val before = original.getJSONObject(row); val after = actual.getJSONObject(row)
                    val retained = strings(after.getJSONArray("icsRoundtrip"))
                    for (line in strings(before.optJSONArray("icsRoundtrip") ?: JSONArray())) {
                        check(line in retained) { "Native calendar import lost a source property" }; rawProperties++
                    }
                    check(semantic(before.opt("icsTimezones")) == semantic(after.opt("icsTimezones"))) { "Native calendar import changed source time zones" }
                    sourceZones += after.optJSONArray("icsTimezones")?.length() ?: 0
                }
                if (actual.length() > 0) {
                    val reexport = ICalendarExport.encode(rows(actual), kind, "UTC")
                    val serializedLines = unfold(reexport)
                    for (row in rows(actual)) for (line in strings(row.getJSONArray("icsRoundtrip"))) {
                        check(line in serializedLines) { "Native calendar reexport changed an authoritative source property" }
                    }
                    compare(original, ICalendarImport.decode(reexport.toByteArray(Charsets.UTF_8), "UTC").document.getJSONArray(group))
                }
            }
            val selected = rows(case.getJSONArray("records")); val kind = case.getString("kind")
            val serialized = ICalendarExport.encode(selected, kind, "UTC")
            val selectedGroup = groups.getValue(kind)
            compare(case.getJSONArray("expected"), ICalendarImport.decode(serialized.toByteArray(Charsets.UTF_8), "UTC").document.getJSONArray(selectedGroup))
            check(serialized.split("\r\n").all { it.toByteArray(Charsets.UTF_8).size <= 75 }) { "Native calendar UTF-8 folding exceeded RFC limit" }
            exportedRecords += selected.size
        }
        val custom = customOffsetAndFiniteRecurrence()
        val aliasRecords = qualifiedTasks()
        val timeZones = systemTimeZones()
        rejectExport { ICalendarExport.encode(listOf(event().put("datum", "2026-03-29").put("zeit", "02:30").put("endZeit", "03:30").put("icsAnzeigeZeitzone", "Europe/Berlin")), "ics-termine") }
        rejectExport {
            ICalendarExport.encode(listOf(event().put("endZeit", "").put("icsNullDauer", true)
                .put("icsRoundtrip", JSONArray().put("DTSTART:20260328T100000Z").put("DURATION:P999999999999999999999999999999D"))), "ics-termine")
        }
        return JSONObject().put("publishedCases", cases.length()).put("importedRecords", importedRecords).put("exportedRecords", exportedRecords)
            .put("retainedSourceProperties", rawProperties).put("retainedTimeZoneBlocks", sourceZones).put("customOffsetSeconds", custom)
            .put("qualifiedTaskRecords", aliasRecords).put("systemTimeZones", timeZones).put("systemZoneApis", 2)
            .put("systemZoneClockChecks", 30).put("maximumProofYear", 8000)
            .put("negativeCases", 2).put("liveNetworkUsed", false).put("fullSyncAccepted", false)
    }

    private fun customOffsetAndFiniteRecurrence(): Int {
        val zone = listOf("BEGIN:VTIMEZONE", "TZID:Private/NativeCalendar", "BEGIN:STANDARD", "DTSTART:19700101T000000", "TZOFFSETFROM:+235959", "TZOFFSETTO:+235959", "END:STANDARD", "END:VTIMEZONE")
        val lines = listOf("BEGIN:VCALENDAR", "VERSION:2.0") + zone + listOf("BEGIN:VEVENT", "UID:native-custom-offset",
            "DTSTART;TZID=Private/NativeCalendar:20260328T100000", "DTEND;TZID=Private/NativeCalendar:20260328T110000", "RRULE:FREQ=DAILY;COUNT=2",
            "X-NATIVE-OPAQUE;X-PARAM=alpha:keep", "SUMMARY:Synthetic custom zone", "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M", "END:VALARM", "END:VEVENT", "END:VCALENDAR")
        val source = lines.joinToString("\r\n", postfix = "\r\n")
        val decoded = ICalendarImport.decode(source.toByteArray(Charsets.UTF_8), "UTC").appointments
        check(decoded.single().getString("datum") == "2026-03-27" && decoded.single().getString("zeit") == "10:00") { "Native custom RFC offset projection mismatch" }
        val encoded = unfold(ICalendarExport.encode(decoded, "ics-termine", "UTC"))
        check("RRULE:FREQ=DAILY;COUNT=2" in encoded && "DTSTART;TZID=Private/NativeCalendar:20260328T100000" in encoded) { "Native finite recurrence was altered" }
        check("TZOFFSETTO:+235959" in encoded && "X-NATIVE-OPAQUE;X-PARAM=alpha:keep" in encoded && "TRIGGER:-PT15M" in encoded) { "Native custom source properties were lost" }
        check(encoded.count { it == "BEGIN:VEVENT" } == 1) { "Native export expanded an event recurrence" }
        return 86399
    }
    private fun qualifiedTasks(): Int {
        val first = JSONObject().put("uid", "same").put("titel", "Synthetic A").put("icsQuelleId", "A")
        val second = JSONObject().put("uid", "same").put("titel", "Synthetic B").put("icsQuelleId", "B")
        val child = JSONObject().put("uid", "child").put("titel", "Synthetic child").put("icsQuelleId", "A")
            .put("elternUid", "same").put("icsElternUid", "same").put("icsElternQuelleId", "B")
        val encoded = ICalendarExport.encode(listOf(first, second, child), "ics-aufgaben", "UTC")
        val result = ICalendarImport.decode(encoded.toByteArray(Charsets.UTF_8), "UTC").tasks
        check(result.map { it.getString("uid") } == listOf("same", "same", "child") && result.map { it.getString("icsQuelleId") } == listOf("A", "B", "A")) { "Native task source aliases did not preserve external identities" }
        check(result[2].getString("icsElternUid") == "same" && result[2].getString("icsElternQuelleId") == "B") { "Native task source-qualified parent changed" }
        check(unfold(encoded).count { it.startsWith("UID:urn:magnolie:task:") } == 2) { "Native colliding task UIDs were not aliased" }
        return result.size
    }
    private fun systemTimeZones(): Int {
        val identifiers = listOf("Europe/Berlin", "America/New_York", "Australia/Sydney", "Australia/Lord_Howe", "Pacific/Chatham")
        for (identifier in identifiers) {
            val zone = ZoneId.of(identifier); val legacy = java.util.TimeZone.getTimeZone(identifier)
            // These five zones have seasonal futures. A provider exposing only
            // a finite/frozen transition table cannot satisfy this native proof.
            check(zone.rules.transitionRules.isNotEmpty()) { "Android provider exposes no verified infinite seasonal future" }
            val definition = TimeZoneExport.definition(identifier)
            check(definition.count { it.startsWith("RRULE:") } == zone.rules.transitionRules.size) { "Native zone future observances were lost" }
            check(definition.none { it.startsWith("RRULE:") && ("COUNT=" in it || "UNTIL=" in it) }) { "Native zone future was bounded" }
            for (year in listOf(2026, 2400, 8000)) for (month in listOf(1, 7)) {
                val wall = LocalDateTime.of(year, month, 15, 12, 0)
                val lines = listOf("BEGIN:VCALENDAR", "VERSION:2.0") + definition + listOf("BEGIN:VEVENT", "UID:native-zone-probe", "DTSTART:20000101T000000Z",
                    "DTSTAMP;TZID=$identifier:" + wall.format(stamp), "SUMMARY:Synthetic timezone probe", "END:VEVENT", "END:VCALENDAR")
                val record = ICalendarImport.decode(lines.joinToString("\r\n", postfix = "\r\n").toByteArray(Charsets.UTF_8), "UTC").appointments.single()
                val actual = wall.toEpochSecond(ZoneOffset.UTC) - record.getLong("geaendert") / 1000
                val expected = zone.rules.getValidOffsets(wall).first()
                val instant = wall.toEpochSecond(expected)
                check(actual == expected.totalSeconds.toLong() && actual == zone.rules.getOffset(Instant.ofEpochSecond(instant)).totalSeconds.toLong()) {
                    "Native generated zone offset differs from Android ZoneRules"
                }
                check(actual == legacy.getOffset(instant * 1000).toLong()) { "Native generated zone offset differs from Android TimeZone" }
            }
        }
        return identifiers.size
    }
}
