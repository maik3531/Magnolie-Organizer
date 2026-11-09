package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.threeten.bp.LocalDateTime
import java.io.ByteArrayInputStream

class ProviderZoneTest {
    private val database get()=ProviderZoneDatabase.bundled
    private fun wall(value:String)=LocalDateTime.parse(value)
    @Test fun resourceIsVerifiedAndCoversApprovedRegistryWithAliases() {
        assertEquals(597,database.identifiers.size);assertEquals("2026egtz",database.version)
        for(id in database.identifiers) assertEquals(id,database.zone(id).identifier)
        val at=ProviderZone.seconds(wall("2074-07-15T09:30:00"))
        assertEquals(10800,database.zone("Asia/Gaza").offsetAt(at))
        assertEquals(wall("2074-07-15T12:30:00"),database.zone("Asia/Gaza").project(at))
        for(id in listOf("UTC","GMT","UT","Z")) assertEquals(0,database.zone(id).offsetAt(at))
        for(id in listOf("Factory","factory","Unknown/Zone","GMT+05:30")) try {database.zone(id);fail("Unknown rules accepted")} catch(_:IllegalArgumentException){}
    }
    @Test fun gapAndFoldPoliciesAreExplicitAndSecondsAreNotRounded() {
        val berlin=database.zone("Europe/Berlin")
        val gap=wall("2026-03-29T02:30:00")
        try {PointResolver.resolve(berlin,gap);fail("Gap accepted")} catch(_:IllegalArgumentException){}
        assertNull(PointResolver.resolve(berlin,gap,PointResolver.Gap.OMIT))
        assertEquals(ProviderZone.seconds(wall("2026-03-29T01:30:00")),PointResolver.resolve(berlin,gap,PointResolver.Gap.FORWARD))
        val fold=wall("2026-10-25T02:30:00")
        assertEquals(3600L,PointResolver.resolve(berlin,fold,fold=PointResolver.Fold.LATER)!!-PointResolver.resolve(berlin,fold)!!)
        try {PointResolver.resolve(berlin,fold,fold=PointResolver.Fold.REJECT);fail("Fold accepted")} catch(_:IllegalArgumentException){}
        val amsterdam=database.zone("Europe/Amsterdam");val old=ProviderZone.seconds(wall("1800-01-01T00:00:00"))
        assertEquals(1172,amsterdam.offsetAt(old))
    }
    @Test fun completePosixRulesUseGregorianCycleAndSignedClocks() {
        val j=ProviderZoneDatabase.parseTail("STD0DST,J60/-2,J300/26")
        assertEquals(wall("2024-02-29T22:00:00"),j.start!!.wall(2024))
        assertEquals(wall("2023-02-28T22:00:00"),j.start!!.wall(2023))
        val n=ProviderZoneDatabase.parseTail("STD0DST,59/167:59:59,300/-167:59:59")
        assertEquals(wall("2024-03-06T23:59:59"),n.start!!.wall(2024))
        val m=ProviderZoneDatabase.parseTail("STD0DST,M12.5.0/167,M1.1.0/-167")
        assertTrue(m.start!!.wall(2024).year>=2024)
        assertEquals(2,m.transitions(9999).size)
    }
    @Test fun boundaryProjectionAndGregorianArithmeticDoNotRequireNamedBpRules() {
        for(id in listOf("Pacific/Kiritimati","America/New_York","Asia/Gaza")) for(year in listOf(1,99,400,2400,9999)) {
            val local=LocalDateTime.of(year,7,15,12,30)
            assertEquals(local,database.zone(id).project(PointResolver.resolve(database.zone(id),local)!!))
        }
        val first=ProviderZone.seconds(wall("0001-01-01T00:00:00"))
        assertEquals(0,database.zone("America/New_York").project(first).year)
    }
    @Test fun hashMismatchAndMalformedFutureFailClosed() {
        try {ProviderZoneDatabase.fromVerifiedStream(ByteArrayInputStream("{}".toByteArray()));fail("Unverified payload accepted")} catch(_:IllegalArgumentException){}
        for(value in listOf("STD0DST","STD0DST,M0.1.0,M10.1.0","STD0DST,J366,J1","STD0DST,366,1","STD0DST,M3.1.0/168,M10.1.0"))
            try {ProviderZoneDatabase.parseTail(value);fail("Malformed tail accepted: $value")} catch(_:IllegalArgumentException){} catch(_:IllegalStateException){}
        val source=ProviderZoneDatabase::class.java.classLoader!!.getResourceAsStream(ProviderZoneDatabase.RESOURCE)!!.use {it.readBytes()}
        val corrupt=source.clone();corrupt[corrupt.lastIndex]=(corrupt.last().toInt() xor 1).toByte()
        try {ProviderZoneDatabase.fromVerifiedStream(ByteArrayInputStream(corrupt));fail("Changed resource accepted")} catch(_:IllegalArgumentException){}
        val invalid=JSONObject(String(source)).also {it.getJSONArray("rules").getJSONArray(0).getJSONArray(3).put(0,123)}
        try {ProviderZoneDatabase.parse(invalid);fail("Inconsistent tail accepted")} catch(_:IllegalArgumentException){}
    }
}
