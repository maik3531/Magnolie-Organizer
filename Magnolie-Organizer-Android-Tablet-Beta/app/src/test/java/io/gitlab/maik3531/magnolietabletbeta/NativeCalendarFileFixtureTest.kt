package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class NativeCalendarFileFixtureTest {
    @Test fun actualSafSourceDecodesToTheInputConsumedByTheSharedUiContract() {
        val fixture=NativeCalendarFileFixture("contract-v1")
        val document=ICalendarImport.decode(fixture.source.toByteArray(Charsets.UTF_8),"UTC",sourceName=fixture.fileName).document
        for(group in listOf("termine","aufgaben","jahrestage")) {
            assertEquals(1,document.getJSONArray(group).length())
            assertEquals(fixture.sourceId,document.getJSONArray(group).getJSONObject(0).getString("icsQuelleId"))
        }
        assertEquals(fixture.taskUid,document.getJSONArray("aufgaben").getJSONObject(0).getString("uid"))
        assertEquals(fixture.sourceSHA256,document.getJSONObject("icsImportMetadata").getString("sourceSHA256"))
        val actual=JSONObject().put("source",fixture.source).put("fileName",fixture.fileName).put("sourceId",fixture.sourceId)
            .put("eventUid",fixture.eventUid).put("taskUid",fixture.taskUid).put("anniversaryUid",fixture.anniversaryUid).put("document",document)
        val recording=System.getenv("NATIVE_CALENDAR_MERGE_RECORD")
        if(recording!=null) File(recording).writeText(actual.toString(2)+"\n")
        else {
            val stream=javaClass.classLoader!!.getResourceAsStream("calendar-files-native-merge.json") ?: error("Missing actual native file import contract")
            val expected=stream.bufferedReader().use {JSONObject(it.readText())}
            assertTrue("Production decoder drifted from shared UI contract input",expected.similar(actual))
        }
    }
}
