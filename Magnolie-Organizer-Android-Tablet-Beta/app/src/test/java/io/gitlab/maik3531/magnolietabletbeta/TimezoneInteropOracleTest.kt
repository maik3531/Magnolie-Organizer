package io.gitlab.maik3531.magnolietabletbeta

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/** Independent host references for the asset consumed by the actual WebView audit. */
class TimezoneInteropOracleTest {
    @Test fun publishedPythonClocksMatchBundledProviderWithIndependentJavaTimeVersionReport() {
        val root=File(System.getProperty("tablet.root") ?: "Magnolie-Organizer-Android-Tablet-Beta")
        val bytes=File(root,"../port-adapters/tests/timezone-interop-oracle.json").readBytes()
        val hash=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {"%02x".format(it.toInt() and 255)}
        assertEquals("03c3278c744c8e121c3cdb4d1b6f7b3518adebdb10bca36affb3b7a6def72238",hash)
        val fixture=JSONObject(bytes.toString(Charsets.UTF_8))
        assertEquals("2.0.30",fixture.getString("publishedVersion"))
        assertEquals(TimeZoneExport.databaseVersion,fixture.getString("expectedBundledTZDBVersion"))
        val clocks=fixture.getJSONArray("clocks"); assertEquals(37,clocks.length())
        val identifiers=mutableSetOf<String>(); val years=mutableSetOf<Int>(); val mismatches=mutableListOf<String>()
        for(index in 0 until clocks.length()) {
            val row=clocks.getJSONObject(index); val name=row.getString("identifier"); val text=row.getString("wall")
            identifiers.add(name); years.add(text.take(4).toInt())
            val bundled=org.threeten.bp.LocalDateTime.parse(text).atZone(org.threeten.bp.ZoneId.of(name))
            val native=java.time.LocalDateTime.parse(text).atZone(java.time.ZoneId.of(name))
            assertEquals(name+text,row.getLong("epochMs"),bundled.toInstant().toEpochMilli())
            assertEquals(row.getInt("offsetSeconds"),bundled.offset.totalSeconds)
            if (row.getLong("epochMs")!=native.toInstant().toEpochMilli())
                mismatches.add(name+text+" Python="+row.getInt("offsetSeconds")+" BP="+bundled.offset.totalSeconds+" JDK="+native.offset.totalSeconds)
        }
        // The independently installed host JDK may carry older normative IANA data.
        // Native WebView acceptance still fails on every such disagreement.
        println("Independent host JDK TZDB="+java.time.zone.ZoneRulesProvider.getVersions("Africa/Casablanca").lastKey()+
            "; normative IANA="+fixture.getString("ianaVersion")+"; differences="+mismatches.joinToString("; "))
        assertEquals(9,identifiers.size); assertEquals(setOf(2026,2400),years)
    }
}
