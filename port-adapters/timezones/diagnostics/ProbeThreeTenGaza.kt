package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import org.threeten.bp.Instant
import org.threeten.bp.ZoneId
import java.io.File

/** Public synthetic evidence for the pinned provider defect; not an expected-success test. */
fun main(args: Array<String>) {
    require(args.size==2) {"Actual saved UI fixture and diagnostic output directory required"}
    val out=File(args[1]).apply {mkdirs()}; val rules=ZoneId.of("Asia/Gaza").rules
    val report=JSONObject().put("provider","org.threeten:threetenbp:1.7.5")
        .put("tzdbVersion",org.threeten.bp.zone.ZoneRulesProvider.getVersions("Asia/Gaza").lastKey())
    val instant=Instant.parse("2074-07-15T09:30:00Z")
    report.put("directOffsetSeconds",rules.getOffset(instant).totalSeconds).put("normativeOffsetSeconds",10800)
    val source="BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:public-gaza-provider-diagnostic\r\nSUMMARY:Public timezone diagnostic\r\nDTSTART;TZID=Asia/Gaza:20740715T123000\r\nDURATION:PT1H\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    File(out,"gaza-2074-source.ics").writeText(source)
    try {
        val imported=ICalendarImport.decode(source.toByteArray(),"UTC").appointments.single()
        report.put("importStatus","accepted").put("importUTCDate",imported.getString("datum"))
            .put("importUTCTime",imported.getString("zeit")).put("normativeUTCTime","09:30")
    } catch(failure:IllegalArgumentException) {report.put("importStatus","rejected").put("importError",failure.message)}
    val record=JSONObject(File(args[0]).readText()).getJSONArray("records").getJSONObject(0)
        .put("datum","2074-07-15").put("endDatum","2074-07-15").put("zeit","12:30").put("endZeit","13:30").put("icsAnzeigeZeitzone","Asia/Gaza")
    try {
        val encoded=ICalendarExport.encode(listOf(record),"ics-termine","Asia/Gaza")
        File(out,"gaza-2074-export.ics").writeText(encoded)
        report.put("exportStatus","accepted").put("exportBytes",encoded.toByteArray().size)
        try {
            val back=ICalendarImport.decode(encoded.toByteArray(),"UTC").appointments.single()
            report.put("reimportStatus","accepted").put("reimportUTCTime",back.getString("zeit"))
        } catch(failure:IllegalArgumentException) {report.put("reimportStatus","rejected").put("reimportError",failure.message)}
    } catch(failure:IllegalArgumentException) {report.put("exportStatus","rejected").put("exportError",failure.message)}
    File(out,"production-codec-report.json").writeText(report.toString(2));println(report)
}
