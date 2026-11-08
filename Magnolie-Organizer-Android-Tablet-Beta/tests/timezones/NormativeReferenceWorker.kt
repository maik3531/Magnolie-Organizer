package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.threeten.bp.LocalDateTime

/** Offline independent-oracle adapter. Milliseconds exist only at this boundary. */
fun main() {
    val database=ProviderZoneDatabase.bundled
    generateSequence(::readLine).forEach { line ->
        val rows=JSONArray(line);val failures=JSONArray()
        for(i in 0 until rows.length()) {
            val row=rows.getJSONArray(i)
            try {
                val zone=database.zone(row.getString(1))
                if(row.getString(0)=="o") {
                    val ms=row.getLong(2);val epoch=Math.floorDiv(ms,1000);val remainder=Math.floorMod(ms,1000).toInt()
                    check(zone.offsetAt(epoch)==row.getInt(3)) {"offset mismatch"}
                    val wall=zone.project(epoch)
                    val actual=JSONArray(listOf(wall.year,wall.monthValue,wall.dayOfMonth,wall.hour,wall.minute,wall.second,remainder))
                    check(actual.toString()==row.getJSONArray(4).toString()) {"wall mismatch: $actual"}
                } else {
                    val p=row.getJSONArray(2);val millis=p.getInt(6)
                    val wall=LocalDateTime.of(p.getInt(0),p.getInt(1),p.getInt(2),p.getInt(3),p.getInt(4),p.getInt(5))
                    val expected=row.getJSONArray(3)
                    if(expected.length()>0) {
                        check(PointResolver.resolve(zone,wall)!!*1000+millis==expected.getLong(0)) {"earlier mismatch"}
                        check(PointResolver.resolve(zone,wall,fold=PointResolver.Fold.LATER)!!*1000+millis==expected.getLong(expected.length()-1)) {"later mismatch"}
                        if(expected.length()>1) {
                            var rejected=false
                            try {PointResolver.resolve(zone,wall,fold=PointResolver.Fold.REJECT)} catch(_:IllegalArgumentException){rejected=true}
                            check(rejected) {"fold not rejected"}
                        }
                    } else {
                        var rejected=false
                        try {PointResolver.resolve(zone,wall)} catch(_:IllegalArgumentException){rejected=true}
                        check(rejected) {"gap not rejected"}
                        check(PointResolver.resolve(zone,wall,PointResolver.Gap.OMIT)==null)
                        check(PointResolver.resolve(zone,wall,PointResolver.Gap.FORWARD)!!*1000+millis==row.getLong(4)) {"gap-forward mismatch"}
                    }
                }
            } catch(error:Exception) {failures.put(JSONObject().put("identifier",row.opt(1)).put("sample",row).put("error",error.toString()))}
        }
        println(JSONObject().put("checked",rows.length()).put("failures",failures))
    }
}
