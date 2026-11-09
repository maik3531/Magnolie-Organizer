package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CalendarExportRequestTest {
    private fun envelope(kind: String) = JSONObject().put("cmd","tablet_export_ics").put("art",kind)
        .put("session","current-page").put("revision","persisted-book").put("requestId","export-1")
    @Test fun eachActionReadsOnlyItsWholeAuthoritativeBookCollection() {
        val book = JSONObject().put("termine",JSONArray().put(JSONObject().put("id","appointment")))
            .put("aufgaben",JSONArray().put(JSONObject().put("id","task")))
            .put("jahrestage",JSONArray().put(JSONObject().put("id","anniversary")))
        val before = book.toString()
        for ((kind,id) in listOf("ics-termine" to "appointment","ics-aufgaben" to "task","ics-jahrestage" to "anniversary")) {
            val request = CalendarExportRequest.parse(envelope(kind))
            assertEquals(id,request.records(book).single().getString("id"))
            assertTrue(request.fileName.endsWith(".ics"))
        }
        assertEquals(before,book.toString())
    }
    @Test fun unsupportedKindsFrontendBodiesAndCoercedAuthorityRejectBeforeEncoding() {
        for (message in listOf(envelope("csv-termine"),envelope("ics-termine").put("daten",JSONArray()),
            envelope("ics-termine").put("ids",JSONArray()),envelope("ics-termine").put("requestId",1),
            envelope("ics-termine").put("session",JSONObject.NULL),envelope("ics-termine").put("revision",""))) {
            try { CalendarExportRequest.parse(message); fail("Invalid ICS export request accepted") } catch (_: IllegalArgumentException) { } catch (_: IllegalStateException) { }
        }
    }
    @Test fun invalidOrEmptyNativeRecordsCannotCreateAFile() {
        val request=CalendarExportRequest.parse(envelope("ics-termine"))
        for (records in listOf(JSONArray(),JSONArray().put("not an object"))) {
            try { request.records(JSONObject().put("termine",records)); fail("Invalid native records accepted") }
            catch (_: IllegalArgumentException) { } catch (_: IllegalStateException) { }
        }
    }
    @Test fun icsAndJsonExportsHaveIndependentExplicitFormatsAndOneShotResults() {
        val routes=DocumentRequests(); val session=DocumentSession("page","saved")
        val ics=routes.begin(true,1,session,requestId="ics",exportFormat=ExportFormat.ICS)
        assertEquals(ExportFormat.ICS,ics.exportFormat)
        assertEquals(ics,routes.take(ics.code,1,session)); assertTrue(routes.finish(ics.code))
        assertNull(routes.take(ics.code,1,session)); assertFalse(routes.finish(ics.code))
        val json=routes.begin(true,1,session)
        assertEquals(ExportFormat.JSON,json.exportFormat); routes.cancel()
        assertNull(routes.take(json.code,1,session)); assertFalse(routes.isActive(ics))
    }
    @Test fun documentWriteFlushAndCloseFailuresNeverReturnSuccessfulCompletion() {
        for (phase in listOf("write","flush","close")) {
            val output=object : java.io.OutputStream() {
                override fun write(value: Int) { if (phase=="write") throw java.io.IOException("Synthetic write failure") }
                override fun flush() { if (phase=="flush") throw java.io.IOException("Synthetic flush failure") }
                override fun close() { if (phase=="close") throw java.io.IOException("Synthetic close failure") }
            }
            try { CalendarExportRequest.write(output,"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"); fail("Provider failure returned success") }
            catch (_: java.io.IOException) { }
        }
        val bytes=java.io.ByteArrayOutputStream()
        CalendarExportRequest.write(bytes,"Synthetic ü")
        assertEquals("Synthetic ü",bytes.toString("UTF-8"))
        try { CalendarExportRequest.write(null,"fixture"); fail("Missing provider stream accepted") }
        catch (_: IllegalArgumentException) { }
    }

}
