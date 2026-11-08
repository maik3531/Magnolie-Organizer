package io.gitlab.maik3531.magnolietabletbeta

import android.content.Context
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import org.threeten.bp.LocalDateTime
import org.threeten.bp.ZoneOffset
import org.threeten.bp.format.DateTimeFormatter
import java.util.Locale

/** Production calendar codecs on Android's actual org.json and verified normative provider.
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

    /** Read the actual installed target APK, then exercise its production singleton.
     * No test-supplied data is passed to a production database constructor. */
    fun providerIdentity(targetContext: Context): JSONObject {
        check(targetContext.packageName == "io.gitlab.maik3531.magnolieorganizer.tablet.beta") { "Expected the installed production target context" }
        val bytes = java.util.zip.ZipFile(targetContext.applicationInfo.sourceDir).use { apk ->
            val entry = apk.getEntry(ProviderZoneDatabase.RESOURCE) ?: error("Normative resource missing from the target APK")
            check(entry.size == 428473L) { "Unexpected packaged normative resource size" }
            apk.getInputStream(entry).use { it.readBytes() }
        }
        check(hash(bytes) == ProviderZoneDatabase.PAYLOAD_SHA256) { "Installed target APK normative resource checksum mismatch" }
        val database = ProviderZoneDatabase.bundled
        check(database.version == "2026egtz" && database.payloadSHA256 == hash(bytes) && database.identifiers.size == 597)
        return JSONObject().put("provider", "normative-tzif-posix").put("version", database.version)
            .put("payloadSHA256", database.payloadSHA256).put("resource", ProviderZoneDatabase.RESOURCE)
            .put("resourceInTargetAPK", true).put("namedZones", database.identifiers.size)
    }

    fun run(instrumentationContext: Context, targetContext: Context): JSONObject {
        check(Looper.myLooper() != Looper.getMainLooper()) { "Native calendar checks require the instrumentation worker" }
        check(DisposableEmulatorPolicy.accepts(android.os.Build.FINGERPRINT, android.os.Build.MODEL, android.os.Build.BRAND)) { "Disposable emulator required" }
        // Context is Instrumentation.context, never targetContext: this asset is
        // part of the test APK and must not enter the application's shipped assets.
        val provider = providerIdentity(targetContext)
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
        val timeZones = systemTimeZones(instrumentationContext)
        val gazaCases = gazaProductCodecs()
        rejectExport { ICalendarExport.encode(listOf(event().put("datum", "2026-03-29").put("zeit", "02:30").put("endZeit", "03:30").put("icsAnzeigeZeitzone", "Europe/Berlin")), "ics-termine") }
        rejectExport {
            ICalendarExport.encode(listOf(event().put("endZeit", "").put("icsNullDauer", true)
                .put("icsRoundtrip", JSONArray().put("DTSTART:20260328T100000Z").put("DURATION:P999999999999999999999999999999D"))), "ics-termine")
        }
        return JSONObject().put("publishedCases", cases.length()).put("importedRecords", importedRecords).put("exportedRecords", exportedRecords)
            .put("retainedSourceProperties", rawProperties).put("retainedTimeZoneBlocks", sourceZones).put("customOffsetSeconds", custom)
            .put("qualifiedTaskRecords", aliasRecords).put("systemTimeZones", timeZones)
            .put("timeZoneProvider", "normative-tzif-posix").put("timeZoneProviderIdentity", provider)
            .put("timeZoneDatabaseVersion", ProviderZoneDatabase.bundled.version)
            .put("gazaProductCodecCases", gazaCases)
            .put("systemZoneClockChecks", 30).put("legacyOsOffsetComparisons", if (android.os.Build.VERSION.SDK_INT >= 26) 30 else 10)
            .put("maximumProofYear", 8000)
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
    private fun gazaProductCodecs(): Int {
        val source = listOf("BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:native-gaza-provider-regression",
            "SUMMARY:Synthetic Gaza codec regression", "DTSTART;TZID=Asia/Gaza:20740715T123000", "DURATION:PT1H", "END:VEVENT", "END:VCALENDAR")
        val imported = ICalendarImport.decode(source.joinToString("\r\n", postfix="\r\n").toByteArray(Charsets.UTF_8), "UTC").appointments.single()
        check(imported.getString("datum") == "2074-07-15" && imported.getString("zeit") == "09:30") { "Production import used the defective BP Gaza offset" }
        val fresh = event().put("datum", "2074-07-15").put("endDatum", "2074-07-15")
            .put("zeit", "12:30").put("endZeit", "13:30").put("icsAnzeigeZeitzone", "Asia/Gaza")
        val encoded = ICalendarExport.encode(listOf(fresh), "ics-termine", "Asia/Gaza")
        check("DTSTART;TZID=Asia/Gaza:20740715T123000" in unfold(encoded))
        val back = ICalendarImport.decode(encoded.toByteArray(Charsets.UTF_8), "UTC").appointments.single()
        check(back.getString("datum") == "2074-07-15" && back.getString("zeit") == "09:30") { "Production export retained the defective BP Gaza offset" }
        return 2
    }

    private fun systemTimeZones(instrumentationContext: Context): Int {
        val bytes = instrumentationContext.assets.open("timezone-native-tzdb-oracle.json").use { it.readBytes() }
        check(hash(bytes) == "74551065e797d10df72caa7f82a13bfb8d923e2f33a16546728cd6ecf7bfb5cf") { "Native timezone oracle checksum mismatch" }
        val oracle = JSONObject(bytes.toString(Charsets.UTF_8))
        check(oracle.getString("canonicalCommit") == "067c38934b539943d8e1720abafd8a80b401d797" &&
            oracle.getString("expectedBundledTZDBVersion") == TimeZoneExport.databaseVersion) { "Native timezone oracle/provider version mismatch" }
        val clocks = oracle.getJSONArray("clocks"); check(clocks.length() == 30)
        val identifiers = listOf("Europe/Berlin", "America/New_York", "Australia/Sydney", "Australia/Lord_Howe", "Pacific/Chatham")
        var verified = 0
        for (identifier in identifiers) {
            val zone = ProviderZoneDatabase.bundled.zone(identifier); val legacy = java.util.TimeZone.getTimeZone(identifier)
            check(zone.model.tail.start != null && zone.model.tail.end != null) { "Bundled provider exposes no verified infinite seasonal future" }
            val definition = TimeZoneExport.definition(identifier)
            check(definition.count { it.startsWith("RRULE:") } >= 2) { "Native zone future observances were lost" }
            check(definition.none { it.startsWith("RRULE:") && ("COUNT=" in it || "UNTIL=" in it) }) { "Native zone future was bounded" }
            for (index in 0 until clocks.length()) {
                val clock = clocks.getJSONObject(index)
                if (clock.getString("identifier") != identifier) continue
                val year = clock.getInt("year")
                val wall = LocalDateTime.of(year, clock.getInt("month"), clock.getInt("day"), clock.getInt("hour"), clock.getInt("minute"))
                val lines = listOf("BEGIN:VCALENDAR", "VERSION:2.0") + definition + listOf("BEGIN:VEVENT", "UID:native-zone-probe", "DTSTART:20000101T000000Z",
                    "DTSTAMP;TZID=$identifier:" + wall.format(stamp), "SUMMARY:Synthetic timezone probe", "END:VEVENT", "END:VCALENDAR")
                val record = ICalendarImport.decode(lines.joinToString("\r\n", postfix = "\r\n").toByteArray(Charsets.UTF_8), "UTC").appointments.single()
                val actual = wall.toEpochSecond(ZoneOffset.UTC) - record.getLong("geaendert") / 1000
                val instant = zone.validInstants(wall).first()
                val expected = wall.toEpochSecond(ZoneOffset.UTC) - instant
                check(actual == clock.getLong("offsetSeconds") && actual == expected &&
                    actual == zone.offsetAt(instant).toLong()) {
                    "Native generated timezone differs from the independent published Python oracle or bundled rules"
                }
                // API23 OS data may itself freeze after 2038. Never replace the
                // complete bundled future with that limited legacy API. Core
                // checks against the independent oracle always run for all 30 clocks.
                if (android.os.Build.VERSION.SDK_INT >= 26 || year == 2026) {
                    check(actual == legacy.getOffset(instant * 1000).toLong()) { "Native generated timezone differs from the public OS offset API" }
                }
                verified++
            }
        }
        check(verified == 30) { "Native timezone oracle clocks were omitted" }
        return identifiers.size
    }
}
