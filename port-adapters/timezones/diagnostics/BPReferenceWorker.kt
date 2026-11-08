import org.json.JSONArray
import org.json.JSONObject
import org.threeten.bp.*

/** Direct unmodified-provider comparator. It neither uses nor reads the JS payload. */
fun main() {
    generateSequence(::readLine).forEach { line ->
        val rows=JSONArray(line);val failures=JSONArray()
        for(index in 0 until rows.length()) {
            val row=rows.getJSONArray(index);val name=row.getString(1)
            try {
                val zone=ZoneId.of(name);val rules=zone.rules
                if(row.getString(0)=="o") {
                    val instant=Instant.ofEpochMilli(row.getLong(2));val offset=rules.getOffset(instant).totalSeconds
                    require(offset==row.getInt(3)) {"BP offset=$offset, normative=${row.getInt(3)}"}
                    val p=LocalDateTime.ofInstant(instant,zone);val actual=listOf(p.year,p.monthValue,p.dayOfMonth,p.hour,p.minute,p.second,p.nano/1_000_000)
                    val expected=row.getJSONArray(4);require(actual.indices.all {actual[it]==expected.getInt(it)}) {"BP wall parts disagree"}
                } else {
                    val p=row.getJSONArray(2);val wall=LocalDateTime.of(p.getInt(0),p.getInt(1),p.getInt(2),p.getInt(3),p.getInt(4),p.getInt(5),p.getInt(6)*1_000_000)
                    val expected=row.getJSONArray(3);val actual=rules.getValidOffsets(wall).map {wall.toInstant(it).toEpochMilli()}.distinct().sorted()
                    require(actual.size==expected.length() && actual.indices.all {actual[it]==expected.getLong(it)}) {"BP wall candidates=$actual, normative=$expected"}
                    if(actual.isEmpty()) {
                        val transition=rules.getTransition(wall);require(transition!=null && transition.isGap) {"BP gap transition missing"}
                        require(wall.toInstant(transition.offsetBefore).toEpochMilli()==row.getLong(4)) {"BP forward-gap offset disagrees"}
                    }
                }
            } catch(failure:RuntimeException) {failures.put(JSONObject().put("identifier",name).put("sample",row).put("error",failure.toString()))}
        }
        println(JSONObject().put("checked",rows.length()).put("failures",failures))
    }
}
