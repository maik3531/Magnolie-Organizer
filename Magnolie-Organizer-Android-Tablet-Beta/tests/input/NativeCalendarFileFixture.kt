package io.gitlab.maik3531.magnolietabletbeta

import java.security.MessageDigest

/** One synthetic source for actual SAF and decoder→shared-merge contract tests. */
internal class NativeCalendarFileFixture(token: String) {
    init {require(token.matches(Regex("[A-Za-z0-9-]{1,64}")))}
    val fileName="native-calendar-import.ics"
    val eventUid="native-files-event-$token"
    val taskUid="native-files-task-$token"
    val anniversaryUid="native-files-anniversary-$token"
    val calendarName="Synthetic calendar files $token"
    val source=listOf("BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Magnolie Native Calendar Files Test//EN","X-WR-CALNAME:$calendarName",
        "X-NATIVE-CALENDAR-HEADER:preserve","BEGIN:VEVENT","UID:$eventUid","DTSTART:20300401T100000Z","DTEND:20300401T110000Z",
        "RRULE:FREQ=DAILY;COUNT=3","RDATE:20300405T100000Z","EXDATE:20300402T100000Z","SUMMARY:Synthetic calendar files appointment",
        "X-NATIVE-CALENDAR-OPAQUE;X-PARAM=alpha:keep","BEGIN:VALARM","ACTION:DISPLAY","TRIGGER:-PT15M","DESCRIPTION:Synthetic native alarm","END:VALARM","END:VEVENT",
        "BEGIN:VTODO","UID:$taskUid","DUE;VALUE=DATE:20300406","SUMMARY:Synthetic calendar files task","PRIORITY:1","END:VTODO",
        "BEGIN:VEVENT","UID:$anniversaryUid","DTSTART;VALUE=DATE:19800229","RRULE:FREQ=YEARLY","X-MAGNOLIE-TYPE-ID:birthday",
        "SUMMARY:Synthetic calendar files anniversary","END:VEVENT","END:VCALENDAR").joinToString("\r\n",postfix="\r\n")
    val sourceSHA256=hash(source)
    val sourceId="ics:"+hash("$fileName\n$calendarName")
    private fun hash(value:String)=MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") {"%02x".format(java.util.Locale.ROOT,it.toInt() and 255)}
}
