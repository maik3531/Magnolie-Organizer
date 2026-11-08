package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test
import org.threeten.bp.Instant
import org.threeten.bp.LocalDateTime
import org.threeten.bp.ZoneId

/** JVM references here are independent of the production ThreeTen namespace.
 * These checks do not claim Android SDK/runtime or old-device acceptance. */
class TzdbBackportTest {
    @Test fun bundledProviderHasPinnedPublicVersionAndRealHistoryAndFuture() {
        assertEquals("2026egtz", TimeZoneExport.databaseVersion)
        for (name in listOf("Europe/Berlin", "America/New_York", "Australia/Sydney", "Australia/Lord_Howe", "Pacific/Chatham")) {
            val rules = ZoneId.of(name).rules
            assertTrue(name, rules.transitions.isNotEmpty()); assertTrue(name, rules.transitionRules.isNotEmpty())
            assertTrue(TimeZoneExport.definition(name).any { it.startsWith("RRULE:") })
        }
    }
    @Test fun checkedInSupplyChainRecordMatchesThePackagedDatabaseAndRetainedLicense() {
        val root = java.io.File(System.getProperty("tablet.root") ?: "Magnolie-Organizer-Android-Tablet-Beta")
        val record = org.json.JSONObject(java.io.File(root, "third-party/threetenbp-1.7.5.json").readText())
        assertEquals("org.threeten:threetenbp", record.getString("module")); assertEquals("1.7.5", record.getString("version"))
        assertEquals(TimeZoneExport.databaseVersion, record.getString("tzdbVersion"))
        fun sha(bytes: ByteArray) = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        val database = ZoneId::class.java.classLoader!!.getResourceAsStream(record.getString("tzdbResource"))
            ?: throw AssertionError("The complete bundled TZDB resource is missing")
        assertEquals(record.getString("tzdbResourceSHA256"), database.use { sha(it.readBytes()) })
        assertEquals(record.getString("licenseSHA256"), sha(java.io.File(root, record.getString("retainedLicense")).readBytes()))
    }
    @Test fun nativeGoldenFutureClocksMatchTheActualPublishedPythonOracle() {
        val root = java.io.File(System.getProperty("tablet.root") ?: "Magnolie-Organizer-Android-Tablet-Beta")
        val asset = java.io.File(root, "app/src/androidTest/assets/timezone-native-tzdb-oracle.json")
        val bytes = asset.readBytes()
        val sha = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        assertEquals("74551065e797d10df72caa7f82a13bfb8d923e2f33a16546728cd6ecf7bfb5cf", sha)
        val fixture = org.json.JSONObject(bytes.toString(Charsets.UTF_8))
        assertEquals(TimeZoneExport.databaseVersion, fixture.getString("expectedBundledTZDBVersion"))
        val clocks = fixture.getJSONArray("clocks"); assertEquals(30, clocks.length())
        for (index in 0 until clocks.length()) {
            val row = clocks.getJSONObject(index)
            val wall = LocalDateTime.of(row.getInt("year"), row.getInt("month"), row.getInt("day"), row.getInt("hour"), row.getInt("minute"))
            val expected = row.getInt("offsetSeconds")
            val actual = ZoneId.of(row.getString("identifier")).rules.getOffset(Instant.ofEpochSecond(wall.toEpochSecond(org.threeten.bp.ZoneOffset.ofTotalSeconds(expected))))
            assertEquals(expected, actual.totalSeconds)
        }
    }
    @Test fun completeDatabaseMatchesIndependentJavaTimeHistoryAndWideFuture() {
        for (name in listOf("Europe/Berlin", "America/New_York", "Australia/Sydney", "Australia/Lord_Howe", "Pacific/Chatham", "Asia/Kathmandu", "Etc/UTC")) {
            val bundled = ZoneId.of(name).rules; val native = java.time.ZoneId.of(name).rules
            for (year in listOf(2, 1800, 1900, 1945, 1970, 2000, 2026, 2038, 2100, 2400, 8000)) for (month in 1..12) {
                val reference = java.time.LocalDateTime.of(year, month, 15, 12, 0).toInstant(java.time.ZoneOffset.UTC)
                val actual = bundled.getOffset(Instant.ofEpochSecond(reference.epochSecond)).totalSeconds
                assertEquals("$name year=$year month=$month", native.getOffset(reference).totalSeconds, actual)
            }
        }
    }
    @Test fun gapsAndFoldsUseCompleteRulesIncludingRamadanTransitionsWithinNinetyDays() {
        val cases = mapOf(
            "Africa/Casablanca" to listOf("2026-02-15T02:30", "2026-03-22T02:30"),
            "Europe/Berlin" to listOf("2026-03-29T02:30", "2026-10-25T02:30"),
            "America/New_York" to listOf("2026-03-08T02:30", "2026-11-01T01:30"),
            "Australia/Lord_Howe" to listOf("2026-04-05T01:45", "2026-10-04T02:15"))
        for ((name, clocks) in cases) for (text in clocks) {
            val bundled = ZoneId.of(name).rules.getValidOffsets(LocalDateTime.parse(text)).map { it.totalSeconds }
            val reference = java.time.ZoneId.of(name).rules.getValidOffsets(java.time.LocalDateTime.parse(text)).map { it.totalSeconds }
            assertEquals("$name $text", reference, bundled)
        }
        assertTrue(ZoneId.of("Africa/Casablanca").rules.getValidOffsets(LocalDateTime.parse("2026-03-22T02:30")).isEmpty())
        val source = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:gap\r\nDTSTART;TZID=Africa/Casablanca:20260322T023000\r\nSUMMARY:Synthetic gap\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        try { ICalendarImport.decode(source.toByteArray(), "UTC"); fail("A DST gap cannot become an imported appointment") }
        catch (_: ICalendarImport.ImportException) { }
    }
}
