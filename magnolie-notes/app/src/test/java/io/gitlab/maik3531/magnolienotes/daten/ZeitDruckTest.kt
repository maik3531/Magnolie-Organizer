package io.gitlab.maik3531.magnolienotes.daten

import io.gitlab.maik3531.magnolienotes.ui.ZeitDrucken
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.util.Locale
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE, sdk = [28])
class ZeitDruckTest {
    private val labels = ZeitDruckTexte("Time tracking", "Name", "Date", "Signature", "Total", "Time",
        listOf("Date", "Activity", "Start", "End date", "End", "Hours", "Pause (minutes)", "Total time", "Note", "Clock change (min)"))
    private fun minute(value: String) = Instant.parse(value).epochSecond / 60

    @Test fun reportPreservesOvernightMonthBoundaryDstAndEscapesText() {
        val entry = Zeiteintrag(startMinute = minute("2026-11-01T02:00:00Z"), endMinute = minute("2026-11-01T11:00:00Z"),
            pauseMinutes = 30, zone = "America/New_York", type = "<script>example</script>")
        val html = ZeitDruckvorlage.html(YearMonth.of(2026, 10), setOf(31), listOf(entry), "A & B",
            ZeitKalender(), labels, Locale.US, false)
        assertTrue(html.contains("09:00"))
        assertTrue(html.contains("08:30"))
        assertTrue(html.contains("-60"))
        assertTrue(html.contains("PM"))
        assertTrue(html.contains("AM"))
        assertTrue(html.contains("&lt;script&gt;example&lt;/script&gt;"))
        assertFalse(html.contains("<script>"))
        assertTrue(html.contains("A &amp; B"))
    }

    @Test fun daySelectionExcludesOtherDaysAndDoesNotWrapLongDurations() {
        val first = Zeiteintrag(startMinute = minute("2026-10-01T00:00:00Z"), endMinute = minute("2026-10-08T01:00:00Z"),
            pauseMinutes = 30, zone = "UTC", type = "Included")
        val other = first.copy(id = java.util.UUID.randomUUID().toString(), startMinute = minute("2026-10-09T00:00:00Z"),
            endMinute = minute("2026-10-09T01:00:00Z"), type = "Excluded")
        val html = ZeitDruckvorlage.html(YearMonth.of(2026, 10), setOf(1), listOf(first, other), "",
            ZeitKalender(), labels, Locale.US, true)
        assertTrue(html.contains("168:30"))
        assertTrue(html.contains("Included"))
        assertFalse(html.contains("Excluded"))
        assertTrue(html.contains("table-header-group"))
        assertTrue(html.contains("A4 landscape"))
    }

    @Test fun inheritedRegionAndOffSwitchControlOnlyHolidayClassification() {
        val holiday = ZeitFeiertag("2026-10-31", "Regional fixture", "DE", regions = setOf("DE-TH"))
        val national = ZeitFeiertag("2026-10-03", "National fixture", "DE", nationwide = true)
        val calendar = ZeitKalender(true, "DE", setOf("DE-TH"), listOf(holiday, national)).validate()
        assertEquals(listOf(holiday.name), calendar.names(LocalDate.parse(holiday.date)))
        assertTrue(calendar.copy(regions = setOf("DE-BY")).names(LocalDate.parse(holiday.date)).isEmpty())
        assertEquals(listOf(holiday.name), calendar.copy(regions = emptySet()).names(LocalDate.parse(holiday.date)))
        val off = calendar.copy(enabled = false)
        assertTrue(off.names(LocalDate.parse(national.date)).isEmpty())
        val html = ZeitDruckvorlage.html(YearMonth.of(2026, 10), setOf(3, 4, 31), emptyList(), "", off, labels, Locale.US, true)
        assertTrue(html.contains("<tr class=\"sunday\">"))
        assertFalse(html.contains("<tr class=\"holiday\">"))
        assertFalse(html.contains(holiday.name))
        assertFalse(html.contains(national.name))
    }

    @Test fun printJobStartsWithA4LandscapeAndDocumentMargins() {
        val attributes = ZeitDrucken.attributes()
        assertFalse(attributes.mediaSize!!.isPortrait)
        assertEquals(11690, attributes.mediaSize!!.widthMils)
        assertEquals(8270, attributes.mediaSize!!.heightMils)
        assertEquals(394, attributes.minMargins!!.leftMils)
        assertEquals(394, attributes.minMargins!!.topMils)
    }

    @Test fun reportMonthStaysGregorianAndHistoricalOffsetRoundingMatchesTheMinuteCells() {
        val arabic = ZeitDruckvorlage.html(YearMonth.of(2026, 10), setOf(1), emptyList(), "",
            ZeitKalender(), labels, Locale.forLanguageTag("ar-SA"), false)
        assertTrue(arabic.contains("٢٠٢٦"))
        assertFalse(arabic.contains("١٤٤٨"))
        val entry = Zeiteintrag(startMinute = minute("1972-01-07T00:00:00Z"), endMinute = minute("1972-01-07T02:00:00Z"),
            zone = "Africa/Monrovia")
        val html = ZeitDruckvorlage.html(YearMonth.of(1972, 1), setOf(6), listOf(entry), "",
            ZeitKalender(), labels, Locale.US, true)
        assertTrue(html.contains("23:15"))
        assertTrue(html.contains("<td class=\"number\">45</td>"))
        assertTrue(html.contains("02:00"))
    }
}
