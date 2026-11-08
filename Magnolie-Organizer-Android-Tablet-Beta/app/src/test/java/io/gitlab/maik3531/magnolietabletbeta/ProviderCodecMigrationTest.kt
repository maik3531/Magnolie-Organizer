package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File

/** Production codec regression, using the actual shared editor's saved record shape. */
class ProviderCodecMigrationTest {
    private fun source(clock:String,duration:String="PT1H",definition:List<String> = emptyList())=
        (listOf("BEGIN:VCALENDAR","VERSION:2.0")+definition+listOf("BEGIN:VEVENT","UID:normative-provider-regression",
            "DTSTART$clock","DURATION:$duration","SUMMARY:Public synthetic timezone regression","END:VEVENT","END:VCALENDAR"))
            .joinToString("\r\n",postfix="\r\n").toByteArray(Charsets.UTF_8)
    private fun savedUI():JSONObject {
        val stream=javaClass.classLoader!!.getResourceAsStream("calendar-export-system-zone-ui.json")!!
        return stream.bufferedReader().use {JSONObject(it.readText()).getJSONArray("records").getJSONObject(0)}
    }
    @Test fun actualGaza2074ProductionImportAndSavedUIExportUse0930UtcAndRejectOldContradiction() {
        val imported=ICalendarImport.decode(source(";TZID=Asia/Gaza:20740715T123000"),"UTC").appointments.single()
        assertEquals("09:30",imported.getString("zeit"));assertEquals("10:30",imported.getString("endZeit"))
        val record=savedUI().put("datum","2074-07-15").put("endDatum","2074-07-15")
            .put("zeit","12:30").put("endZeit","13:30").put("icsAnzeigeZeitzone","Asia/Gaza")
        val before=record.toString()
        val output=ICalendarExport.encode(listOf(record),"ics-termine","Asia/Gaza")
        assertEquals(before,record.toString());assertTrue(output.contains("TZID:Asia/Gaza\r\n"))
        assertEquals("09:30",ICalendarImport.decode(output.toByteArray(),"UTC").appointments.single().getString("zeit"))
        System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let {File(it,"normative-gaza-2074.ics").writeText(output)}
        val stale=JSONObject(imported.toString()).put("zeit","10:30").put("endZeit","11:30")
        try {ICalendarExport.encode(listOf(stale),"ics-termine","UTC");fail("Old wrong BP projection accepted")}
        catch(_:ICalendarExport.ExportException){}
    }
    @Test fun daysAreWallDaysHoursElapsedAndDateOnlyNeverResolvesSkippedMidnight() {
        val day=ICalendarImport.decode(source(";TZID=Europe/Berlin:20260328T120000","P1D"),"UTC").appointments.single()
        val hours=ICalendarImport.decode(source(";TZID=Europe/Berlin:20260328T120000","PT24H"),"UTC").appointments.single()
        assertEquals("10:00",day.getString("endZeit"));assertEquals("11:00",hours.getString("endZeit"))
        val date=ICalendarImport.decode(source(";VALUE=DATE:20111230","P1D"),"Pacific/Apia").appointments.single()
        assertEquals("2011-12-30",date.getString("datum"));assertEquals("",date.getString("zeit"))
    }
    @Test fun embeddedDefinitionsOverrideKnownAliasesUnsupportedNamesAndUtcSpelling() {
        for(id in listOf("Asia/Gaza","Factory","UTC","Custom/Local")) {
            val definition=listOf("BEGIN:VTIMEZONE","TZID:$id","BEGIN:STANDARD","DTSTART:00010101T020000",
                "TZOFFSETFROM:+0200","TZOFFSETTO:+0200","END:STANDARD","END:VTIMEZONE")
            val item=ICalendarImport.decode(source(";TZID=$id:20740715T123000",definition=definition),"UTC").appointments.single()
            assertEquals("10:30",item.getString("zeit"))
            val output=ICalendarExport.encode(listOf(item),"ics-termine","UTC")
            for(line in definition) assertTrue(output.contains(line+"\r\n"))
            assertEquals("10:30",ICalendarImport.decode(output.toByteArray(),"UTC").appointments.single().getString("zeit"))
        }
    }
    @Test fun sourceTimezoneMayUseTheImportersFormerPrivateUtcMarker() {
        val id="@magnolie-utc-instant"
        val definition=listOf("BEGIN:VTIMEZONE","TZID:$id","BEGIN:STANDARD","DTSTART:00010101T020000",
            "TZOFFSETFROM:+0200","TZOFFSETTO:+0200","END:STANDARD","END:VTIMEZONE")
        val item=ICalendarImport.decode(source(";TZID=$id:20740715T123000",definition=definition),"UTC").appointments.single()
        assertEquals("10:30",item.getString("zeit"))
        val exported=ICalendarExport.encode(listOf(item),"ics-termine","UTC")
        assertEquals("10:30",ICalendarImport.decode(exported.toByteArray(),"UTC").appointments.single().getString("zeit"))
        assertEquals("12:30",ICalendarImport.decode(source(":20740715T123000Z",definition=definition),"UTC").appointments.single().getString("zeit"))
    }
    @Test fun sourceTimezoneMayUseTheExportersFormerPrivateUtcMarker() {
        val id="@utc"
        val definition=listOf("BEGIN:VTIMEZONE","TZID:$id","BEGIN:STANDARD","DTSTART:00010101T020000",
            "TZOFFSETFROM:+0200","TZOFFSETTO:+0200","END:STANDARD","END:VTIMEZONE")
        val item=ICalendarImport.decode(source(";TZID=$id:20740715T123000",definition=definition),"UTC").appointments.single()
        assertEquals("10:30",item.getString("zeit"))
        val exported=ICalendarExport.encode(listOf(item),"ics-termine","UTC")
        assertEquals("10:30",ICalendarImport.decode(exported.toByteArray(),"UTC").appointments.single().getString("zeit"))
    }
    @Test fun aliasesRemainSpelledAsRequestedAndFloatingSourceStaysFloating() {
        val record=savedUI().put("icsAnzeigeZeitzone","US/Eastern")
        val output=ICalendarExport.encode(listOf(record),"ics-termine","UTC")
        assertTrue(output.contains("DTSTART;TZID=US/Eastern:"));assertTrue(output.contains("TZID:US/Eastern\r\n"))
        val floating=ICalendarImport.decode(source(":20740715T123000"),"Asia/Gaza").appointments.single()
        val exported=ICalendarExport.encode(listOf(floating),"ics-termine","UTC")
        assertTrue(exported.contains("DTSTART:20740715T123000\r\n"));assertFalse(exported.contains("BEGIN:VTIMEZONE"))
    }
    @Test fun everyApprovedIdentifierHasProvenUnlimitedExportRules() {
        val definitions=JSONArray()
        val database=ProviderZoneDatabase.bundled
        for(id in database.identifiers) {
            val definition=TimeZoneExport.definition(id)
            assertEquals("TZID:$id",definition[1])
            assertFalse(definition.any {it.startsWith("RRULE:") && ("UNTIL=" in it || "COUNT=" in it)})
            if(database.zone(id).model.tail.daylightOffset!=null) assertTrue(id,definition.count {it.startsWith("RRULE:")}>=2)
            definitions.put(JSONObject().put("identifier",id).put("definition",JSONArray(definition)))
        }
        System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let {File(it,"normative-all-timezone-definitions.json").writeText(definitions.toString())}
    }
}
