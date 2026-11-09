package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.security.MessageDigest
import java.io.File

class CalendarIdentityTest {
    private fun sha(value:String)=MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") {"%02x".format(it.toInt() and 255)}
    @Test fun canonicalIdentityStringsMatchIndependentPythonBytesWithoutPlatformEscaping() {
        val fixture=javaClass.classLoader!!.getResourceAsStream("calendar-identity-python.json")!!.bufferedReader().use {JSONObject(it.readText())}
        val quotes=fixture.getJSONArray("quotes")
        for(i in 0 until quotes.length()) {
            val row=quotes.getJSONObject(i);assertEquals(row.getString("expected"),CalendarIdentity.quote(row.getString("value")))
        }
        val records=fixture.getJSONArray("recurrences")
        for(i in 0 until records.length()) {
            val row=records.getJSONObject(i);val params=row.getJSONObject("parameters")
            val values=params.keys().asSequence().associateWith {params.getString(it)}
            val text=CalendarIdentity.recurrenceKey(values,row.getString("value"))
            assertEquals(row.getString("expected"),text);assertEquals(row.getString("sha256"),sha(text))
        }
        for(invalid in listOf("\ud800","\udc00","\ud800x")) try {CalendarIdentity.quote(invalid);fail("Invalid scalar string accepted")} catch(_:IllegalArgumentException){}
    }
    @Test fun sourceQualifiedRecurrenceUidMatchesUnchangedPublishedReferenceAcrossReimport() {
        val asset=javaClass.classLoader!!.getResourceAsStream("calendar-import-v2.0.30.json")!!.bufferedReader().use {JSONObject(it.readText())}
        val cases=asset.getJSONArray("cases")
        val case=(0 until cases.length()).map {cases.getJSONObject(it)}.single {it.getString("name")=="caldav-series-resource"}
        val expected=case.getJSONObject("importExpected").getJSONArray("termine").getJSONObject(1).getString("uid")
        assertEquals("caldav-series-1-magnolie-instanz-1201680171431eb3",expected)
        repeat(2) {
            val result=ICalendarImport.decode(case.getString("importSource").toByteArray(),"UTC",sourceName="qualified-series.ics").appointments
            assertEquals(expected,result[1].getString("uid"));assertTrue(result.all {it.getString("icsQuelleId").startsWith("ics:")})
        }
    }
    private fun legacyFixture(): JSONObject {
        val directory=generateSequence(File(System.getProperty("user.dir")).absoluteFile) {it.parentFile}
            .map {File(it,"port-adapters/tests/fixtures")}.firstOrNull {File(it,"legacy-android-alias-evidence.json").isFile()}
            ?: throw AssertionError("Missing shared AOSP identity evidence fixture")
        return JSONObject(File(directory,"legacy-android-alias-evidence.json").readText())
    }
    private fun qualifiedSource(): String {
        val asset=javaClass.classLoader!!.getResourceAsStream("calendar-import-v2.0.30.json")!!.bufferedReader().use {JSONObject(it.readText())}
        val cases=asset.getJSONArray("cases")
        return (0 until cases.length()).map {cases.getJSONObject(it)}.single {it.getString("name")=="caldav-series-resource"}.getString("importSource")
    }
    @Test fun legacyEvidenceQuoteAndFullUIDsMatchActualAOSPBytes() {
        val f=legacyFixture();assertEquals("8772ac80610cd62e906330152b09864c471a0921f199f4b9d670d98050e3d86c",f.getString("aospJSONStringerSHA256"))
        val quotes=f.getJSONArray("quotes")
        for(i in 0 until quotes.length()) {
            val v=quotes.getJSONObject(i)
            assertEquals(v.getString("canonical"),CalendarIdentity.quote(v.getString("value")))
            assertEquals(v.getString("legacyAndroid"),CalendarIdentity.legacyAndroidQuote(v.getString("value")))
        }
        val recurrences=f.getJSONArray("recurrences")
        for(i in 0 until recurrences.length()) {
            val v=recurrences.getJSONObject(i);val p=v.getJSONObject("parameters")
            val parameters=p.keys().asSequence().toList().reversed().associateWith {p.getString(it)}
            val old=CalendarIdentity.legacyAndroidRecurrenceKey(parameters,v.getString("value"))
            val current=CalendarIdentity.recurrenceKey(parameters,v.getString("value"))
            assertEquals(v.getString("legacyAndroid"),old);assertEquals(v.getString("legacySHA256"),sha(old))
            assertEquals(v.getString("canonical"),current);assertEquals(v.getString("canonicalSHA256"),sha(current))
            assertEquals(v.getString("legacyUID"),"public-wire-magnolie-instanz-"+sha(old).take(16))
            assertEquals(v.getString("canonicalUID"),"public-wire-magnolie-instanz-"+sha(current).take(16))
        }
        try {CalendarIdentity.legacyAndroidQuote("\ud800");fail("Invalid scalar accepted")} catch(_:IllegalArgumentException){}
    }
    @Test fun evidenceBindsActualSourceWireRIDAndAppointmentIndexWithoutChangingDTO() {
        val source=qualifiedSource();val result=ICalendarImport.decode(source.toByteArray(),"UTC")
        val proof=result.legacyAndroidAliases!!;assertEquals(sha(source),proof.sourceSHA256);assertEquals(result.sourceSHA256,proof.sourceSHA256)
        assertEquals(result.appointments.size,proof.appointmentCount);assertEquals(1,proof.entries.size)
        val entry=proof.entries.single();assertEquals(1,entry.appointmentIndex)
        assertEquals("caldav-series-1-magnolie-instanz-1201680171431eb3",entry.canonicalUID)
        assertEquals("caldav-series-1-magnolie-instanz-7f5e24178d89f683",entry.legacyUID)
        val row=result.appointments[entry.appointmentIndex]
        assertEquals(row.getString("uid"),entry.canonicalUID);assertEquals(row.getString("icsQuelleId"),entry.sourceID)
        assertEquals(row.getString("icsSerienUid"),entry.wireUID)
        val raw=row.getJSONArray("icsRoundtrip");assertTrue((0 until raw.length()).any {raw.getString(it)==entry.recurrenceLine})
        assertEquals("RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000",entry.recurrenceLine)
        val doc=result.document
        assertFalse(doc.has("legacyAndroidAliases"));assertEquals(setOf("termine","aufgaben","jahrestage","icsImportMetadata"),doc.keys().asSequence().toSet())
        assertEquals(setOf("version","calendarProperties","sourceSHA256"),doc.getJSONObject("icsImportMetadata").keys().asSequence().toSet())
        for(record in result.appointments)assertFalse(record.keys().asSequence().any {it.startsWith("legacy")})
        proof.payload.getJSONArray("entries").getJSONObject(0).put("legacyUID","tampered JSON copy")
        assertEquals(entry.legacyUID,proof.payload.getJSONArray("entries").getJSONObject(0).getString("legacyUID"))
        val renamed=ICalendarImport.decode(source.toByteArray(),"UTC",sourceName="other-name.ics")
        assertEquals(proof.sourceSHA256,renamed.legacyAndroidAliases!!.sourceSHA256)
        assertNotEquals(entry.sourceID,renamed.legacyAndroidAliases!!.entries.single().sourceID)
    }
    @Test fun evidenceIndexesOnlyAppointmentsAndPreservesOpaqueWireUIDs() {
        val prefix="BEGIN:VTODO\nUID:task\nDTSTART:20261102T090000Z\nSUMMARY:Task\nEND:VTODO\n"+
            "BEGIN:VEVENT\nUID:birthday\nDTSTART;VALUE=DATE:20000514\nRRULE:FREQ=YEARLY\nSUMMARY:Birthday\nX-MAGNOLIE-TYPE-ID:birthday\nEND:VEVENT\n"
        val source=qualifiedSource().replaceFirst("BEGIN:VEVENT",prefix+"BEGIN:VEVENT")
        val result=ICalendarImport.decode(source.toByteArray(),"UTC")
        assertEquals(2,result.appointments.size);assertEquals(1,result.tasks.size);assertEquals(1,result.anniversaries.size)
        assertEquals(1,result.legacyAndroidAliases!!.entries.single().appointmentIndex)
        val header="BEGIN:VCALENDAR\nVERSION:2.0\n"
        fun event(uid:String)="BEGIN:VEVENT\nUID:$uid\nRECURRENCE-ID;TZID=Europe/Berlin:20261102T100000\nDTSTART:20261102T113000Z\nSUMMARY:Public\nEND:VEVENT\n"
        val bytes=(header+event("wire-caf\u00e9")+event("wire-cafe\u0301")+"END:VCALENDAR\n").toByteArray()
        val opaque=ICalendarImport.decode(bytes,"UTC",sourceName="opaque.ics")
        val entries=opaque.legacyAndroidAliases!!.entries;assertEquals(2,entries.size)
        assertNotEquals(entries[0].wireUID,entries[1].wireUID)
        for((i,entry) in entries.withIndex()) {assertEquals(i,entry.appointmentIndex);assertTrue(entry.canonicalUID.startsWith(entry.wireUID+"-magnolie-instanz-"));assertTrue(entry.legacyUID.startsWith(entry.wireUID+"-magnolie-instanz-"))}
        val unqualified=ICalendarImport.decode((header+event("one")+"END:VCALENDAR\n").toByteArray(),"UTC")
        assertNull(unqualified.legacyAndroidAliases)
        val utc=(header+event("one").replace("RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000","RECURRENCE-ID:20261102T090000Z")+"END:VCALENDAR\n").toByteArray()
        assertNull(ICalendarImport.decode(utc,"UTC",sourceName="utc.ics").legacyAndroidAliases)
        val master=(header+"BEGIN:VEVENT\nUID:master\nDTSTART:20261102T113000Z\nSUMMARY:Master\nEND:VEVENT\nEND:VCALENDAR\n").toByteArray()
        assertNull(ICalendarImport.decode(master,"UTC",sourceName="master.ics").legacyAndroidAliases)
    }
    @Test fun sidecarBytesShareTheUnchangedProjectionCap() {
        val result=ICalendarImport.decode(qualifiedSource().toByteArray(),"UTC");val proof=result.legacyAndroidAliases!!
        val docSize=result.document.toString().toByteArray(Charsets.UTF_8).size;val sidecarSize=proof.payload.toString().toByteArray(Charsets.UTF_8).size
        ICalendarImport.validateProjection(result.document,null,docSize)
        try {ICalendarImport.validateProjection(result.document,proof,docSize);fail("Sidecar bytes ignored")} catch(_:ICalendarImport.ImportException){}
        ICalendarImport.validateProjection(result.document,proof,docSize+sidecarSize+64)
        try {ICalendarImport.validateProjection(result.document,proof,docSize+sidecarSize+63);fail("Aggregate bound ignored")} catch(_:ICalendarImport.ImportException){}
        try {ICalendarImport.validateProjection(result.document,proof,Int.MIN_VALUE);fail("Negative bound accepted")} catch(_:ICalendarImport.ImportException){}
        assertEquals(96*1024*1024,ICalendarImport.maximumProjectedBytes)
    }

}
