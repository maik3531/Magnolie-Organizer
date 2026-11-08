package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.security.MessageDigest

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
}
