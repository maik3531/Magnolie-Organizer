import org.threeten.bp.*
import org.threeten.bp.zone.ZoneRules
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.zip.GZIPOutputStream
import java.io.ByteArrayOutputStream

fun main(args: Array<String>) {
 require(args.size==1) {"Output JSON path required"}
 val start=System.nanoTime(); val names=ZoneId.getAvailableZoneIds().sorted(); val groups=mutableListOf<ZoneRules>();val ids=JSONObject();val rules=JSONArray(); var transitions=0;var recurring=0;var maxTransitions=0
 for(name in names) {
  val zone=ZoneId.of(name).rules;var index=groups.indexOf(zone)
  if(index<0) {
   index=groups.size;groups.add(zone)
   val history=zone.transitions;val future=zone.transitionRules
   transitions+=history.size;recurring+=future.size;maxTransitions=maxOf(maxTransitions,history.size)
   val h=JSONArray();for(t in history){h.put(t.toEpochSecond());h.put(t.offsetAfter.totalSeconds)}
   val r=JSONArray();for(t in future)r.put(JSONArray(listOf(t.month.value,t.dayOfMonthIndicator,t.dayOfWeek?.value?:0,if(t.isMidnightEndOfDay)1 else 0,t.localTime.toSecondOfDay(),t.timeDefinition.name,t.standardOffset.totalSeconds,t.offsetBefore.totalSeconds,t.offsetAfter.totalSeconds)))
   val initial=if(history.isNotEmpty())history.first().offsetBefore.totalSeconds else zone.getOffset(Instant.EPOCH).totalSeconds
   rules.put(JSONArray().put(initial).put(h).put(r))
  }
  ids.put(name,index)
 }
 val payload=JSONObject().put("schema",1).put("tzdbVersion",org.threeten.bp.zone.ZoneRulesProvider.getVersions("Europe/Berlin").lastKey()).put("zones",ids).put("rules",rules)
 val bytes=payload.toString().toByteArray(); val compressed=ByteArrayOutputStream();GZIPOutputStream(compressed).use{it.write(bytes)}
 File(args[0]).writeBytes(bytes)
 val summary=JSONObject().put("namedZones",names.size).put("uniqueFullRules",groups.size).put("historicalTransitions",transitions).put("futureRules",recurring).put("maxZoneTransitions",maxTransitions).put("jsonBytes",bytes.size).put("gzipBytes",compressed.size()).put("generateMs",(System.nanoTime()-start)/1000000)
 println(summary)
}
