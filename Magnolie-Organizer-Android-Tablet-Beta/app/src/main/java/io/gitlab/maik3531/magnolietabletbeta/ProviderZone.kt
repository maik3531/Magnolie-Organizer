package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.threeten.bp.LocalDate
import org.threeten.bp.LocalDateTime
import org.threeten.bp.ZoneOffset
import java.io.InputStream
import java.security.MessageDigest
import java.util.Collections

/** Named-zone rules are exclusively the checked normative TZif/POSIX payload.
 * BP is used only for ISO Gregorian arithmetic with the explicit zero offset. */
internal class ProviderZone private constructor(val identifier: String, internal val model: Model) {
    internal data class Type(val offset: Int,val daylight: Boolean,val name: String,val standard: Boolean,val utc: Boolean)
    internal data class Transition(val at: Long,val before: Int,val after: Int,val daylight: Boolean)
    internal data class DateRule(val kind: String,val a: Int,val b: Int,val c: Int,val clock: Int) {
        fun wall(year: Int): LocalDateTime {
            val date=when(kind) {
                "M" -> {
                    val first=LocalDate.of(year,a,1)
                    var day=1+(c-first.dayOfWeek.value%7+7)%7+(b-1)*7
                    if(day>first.lengthOfMonth()) day-=7
                    first.withDayOfMonth(day)
                }
                "J" -> LocalDate.of(year,1,1).plusDays((a-1+if(LocalDate.of(year,1,1).isLeapYear && a>=60) 1 else 0).toLong())
                "N" -> LocalDate.of(year,1,1).plusDays(a.toLong())
                else -> error("invalid-timezone-future-rule")
            }
            return date.atStartOfDay().plusSeconds(clock.toLong())
        }
    }
    internal data class Tail(val standardOffset: Int,val standardName: String,val daylightOffset: Int?,val daylightName: String?,
                             val start: DateRule?,val end: DateRule?,val text: String) {
        fun transitions(year: Int): List<Transition> {
            val dst=daylightOffset ?: return emptyList()
            return listOf(Transition(seconds(start!!.wall(year))-standardOffset,standardOffset,dst,true),
                Transition(seconds(end!!.wall(year))-dst,dst,standardOffset,false))
        }
    }
    internal class Model(val initial: Type,types: List<Type>,history: List<Transition>,val tail: Tail) {
        val types: List<Type> = immutable(types)
        val history: List<Transition> = immutable(history)
        val offsets: List<Int> = immutable((types.map {it.offset}+tail.standardOffset+listOfNotNull(tail.daylightOffset)).distinct())
        val boundary: Long get()=history.lastOrNull()?.at ?: Long.MIN_VALUE
        @Volatile private var nearbyCache: Pair<Int,List<Transition>>? = null
        fun nearby(year: Int): List<Transition> {
            nearbyCache?.takeIf {it.first==year}?.let {return it.second}
            val result=immutable((year-1..year+1).flatMap {tail.transitions(it)}.sortedBy {it.at})
            nearbyCache=year to result;return result
        }
    }
    fun offsetAt(epochSeconds: Long): Int {
        checkInstant(epochSeconds)
        var low=0;var high=model.history.size
        while(low<high) {val middle=(low+high) ushr 1;if(model.history[middle].at<=epochSeconds) low=middle+1 else high=middle}
        if(model.tail.daylightOffset!=null && epochSeconds>model.boundary) {
            val recent=model.nearby(fromSeconds(epochSeconds).year).lastOrNull {it.at>model.boundary && it.at<=epochSeconds}
            if(recent!=null) return recent.after
        }
        return if(low==0) model.initial.offset else model.history[low-1].after
    }
    internal fun daylightAt(epochSeconds: Long): Boolean {
        checkInstant(epochSeconds)
        if(epochSeconds>model.boundary) {
            if(model.tail.daylightOffset==null) return false
            model.nearby(fromSeconds(epochSeconds).year).lastOrNull {it.at>model.boundary && it.at<=epochSeconds}?.let {return it.daylight}
        }
        return model.history.lastOrNull {it.at<=epochSeconds}?.daylight ?: model.initial.daylight
    }
    fun project(epochSeconds: Long): LocalDateTime = fromSeconds(epochSeconds+offsetAt(epochSeconds))
    fun validInstants(wall: LocalDateTime): List<Long> {
        require(wall.year in 1..9999 && wall.nano==0) {"invalid-timezone-wall"}
        val value=seconds(wall)
        return immutable(model.offsets.map {value-it}.filter {offsetAt(it).toLong()==value-it}.distinct().sorted())
    }
    internal fun gap(wall: LocalDateTime): Transition? {
        val value=seconds(wall)
        val low=value-model.offsets.maxOrNull()!!;val high=value-model.offsets.minOrNull()!!
        val candidates=model.history.filter {it.at in low..high}+model.nearby(wall.year).filter {it.at>model.boundary}
        return candidates.firstOrNull {it.after>it.before && value>=it.at+it.before && value<it.at+it.after}
    }
    companion object {
        internal fun create(identifier: String,model: Model)=ProviderZone(identifier,model)
        internal fun seconds(wall: LocalDateTime): Long = wall.toEpochSecond(ZoneOffset.UTC)
        internal fun fromSeconds(value: Long): LocalDateTime = LocalDateTime.ofEpochSecond(value,0,ZoneOffset.UTC)
        private val minimum=seconds(LocalDate.of(0,12,29).atStartOfDay())
        private val maximum=seconds(LocalDate.of(10000,1,3).atStartOfDay())
        private fun checkInstant(value: Long) {require(value in minimum..maximum) {"invalid-timezone-instant"}}
        internal fun <T> immutable(values: Collection<T>): List<T> = Collections.unmodifiableList(ArrayList(values))
    }
}

internal object PointResolver {
    enum class Gap { REJECT, FORWARD, OMIT }
    enum class Fold { EARLIER, LATER, REJECT }
    fun resolve(zone: ProviderZone,wall: LocalDateTime,gap: Gap=Gap.REJECT,fold: Fold=Fold.EARLIER): Long? {
        val valid=zone.validInstants(wall)
        if(valid.isNotEmpty()) {
            require(valid.size==1 || fold!=Fold.REJECT) {"ambiguous-timezone-wall"}
            return if(fold==Fold.LATER) valid.last() else valid.first()
        }
        val transition=zone.gap(wall) ?: error("unresolved-timezone-wall")
        return when(gap) {
            Gap.OMIT -> null
            Gap.FORWARD -> ProviderZone.seconds(wall)-transition.before
            Gap.REJECT -> throw IllegalArgumentException("nonexistent-timezone-wall")
        }
    }
}

internal class ProviderZoneDatabase private constructor(models: List<ProviderZone.Model>,names: Map<String,Int>,rejected: Set<String>) {
    val version: String get()="2026egtz"
    val payloadSHA256: String get()=PAYLOAD_SHA256
    private val models=ProviderZone.immutable(models)
    private val names=Collections.unmodifiableMap(LinkedHashMap(names))
    private val rejected=Collections.unmodifiableSet(HashSet(rejected))
    val identifiers: List<String> = ProviderZone.immutable(names.keys.sorted())
    fun zone(identifier: String): ProviderZone {
        require(identifier !in rejected) {"unsupported-time-zone"}
        val model=names[identifier]?.let {models[it]} ?: if(identifier in listOf("UTC","GMT","UT","Z")) zero else null
        return ProviderZone.create(identifier,model ?: throw IllegalArgumentException("unknown-time-zone"))
    }
    companion object {
        const val PAYLOAD_SHA256="2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c"
        const val RESOURCE="normative-timezones/tzdb-2026egtz.json"
        private val zero=ProviderZone.Model(ProviderZone.Type(0,false,"UTC",false,false),listOf(ProviderZone.Type(0,false,"UTC",false,false)),
            emptyList(),ProviderZone.Tail(0,"UTC",null,null,null,null,"UTC0"))
        val bundled: ProviderZoneDatabase by lazy {
            val input=ProviderZoneDatabase::class.java.classLoader?.getResourceAsStream(RESOURCE) ?: error("missing-timezone-database")
            input.use {fromVerifiedStream(it)}
        }
        fun fromVerifiedStream(input: InputStream): ProviderZoneDatabase {
            val output=java.io.ByteArrayOutputStream();val buffer=ByteArray(8192)
            while(true) {val size=input.read(buffer);if(size<0) break;require(size>0) {"invalid-timezone-stream"};output.write(buffer,0,size);require(output.size()<=1_048_576) {"timezone-database-limit"}}
            val bytes=output.toByteArray()
            val hash=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {"%02x".format(it.toInt() and 255)}
            require(hash==PAYLOAD_SHA256) {"timezone-database-hash"}
            return parse(JSONObject(String(bytes,Charsets.UTF_8)))
        }
        private fun integer(value: Any,low: Long,high: Long): Long {
            require(value is Number && value.toDouble().isFinite()) {"invalid-timezone-number"}
            val result=(value as Number).toLong();require(result.toDouble()==value.toDouble() && result in low..high) {"invalid-timezone-number"};return result
        }
        private fun number(row: JSONArray,index: Int,low: Long=Int.MIN_VALUE.toLong(),high: Long=Int.MAX_VALUE.toLong())=integer(row.get(index),low,high).toInt()
        private fun offset(row: JSONArray,index: Int)=number(row,index,-89999,93599)
        private fun flag(row: JSONArray,index: Int)=number(row,index,0,1)==1
        private fun string(row: JSONArray,index: Int): String = (row.get(index) as? String)?.also {require(it.length<=255)} ?: error("invalid-timezone-text")
        internal fun parse(root: JSONObject): ProviderZoneDatabase {
            require(integer(root.get("schema"),2,2)==2L && root.get("tzdbVersion")=="2026egtz") {"invalid-timezone-database"}
            val rows=root.getJSONArray("rules");require(rows.length() in 1..1000)
            val models=(0 until rows.length()).map { index ->
                val row=rows.getJSONArray(index);require(row.length()==4)
                val sourceTypes=row.getJSONArray(1);require(sourceTypes.length() in 1..256)
                val types=(0 until sourceTypes.length()).map {i ->
                    val t=sourceTypes.getJSONArray(i);require(t.length()==5)
                    val name=string(t,2);require(name.all {it.code in 32..126})
                    ProviderZone.Type(offset(t,0),flag(t,1),name,flag(t,3),flag(t,4))
                }
                val initial=types[number(row,0,0,types.lastIndex.toLong())]
                val sourceHistory=row.getJSONArray(2);require(sourceHistory.length()%2==0 && sourceHistory.length()<=200_000)
                var before=initial.offset;var last=Long.MIN_VALUE
                val history=(0 until sourceHistory.length() step 2).map {i ->
                    val at=integer(sourceHistory.get(i),-9007199254740,9007199254740);require(at>last);last=at
                    val type=types[number(sourceHistory,i+1,0,types.lastIndex.toLong())]
                    ProviderZone.Transition(at,before,type.offset,type.daylight).also {before=type.offset}
                }
                val sourceTail=row.getJSONArray(3);require(sourceTail.length()==7)
                val tail=parseTail(string(sourceTail,6))
                fun ruleArray(rule: ProviderZone.DateRule?)=rule?.let {JSONArray(listOf(it.kind,it.a,it.b,it.c,it.clock))} ?: JSONObject.NULL
                val expected=JSONArray().put(tail.standardOffset).put(tail.standardName).put(tail.daylightOffset ?: JSONObject.NULL)
                    .put(tail.daylightName ?: JSONObject.NULL).put(ruleArray(tail.start)).put(ruleArray(tail.end)).put(tail.text)
                require(expected.toString()==sourceTail.toString()) {"inconsistent-timezone-future"}
                require(tail.daylightOffset!=null || before==tail.standardOffset) {"invalid-timezone-fixed-future"}
                ProviderZone.Model(initial,types,history,tail)
            }
            val sourceNames=root.getJSONObject("zones");require(sourceNames.length() in 1..1000)
            val names=sourceNames.keys().asSequence().associateWith { name ->
                require(name.matches(Regex("[A-Za-z0-9_+./-]{1,255}")) && !name.contains(".."))
                integer(sourceNames.get(name),0,models.lastIndex.toLong()).toInt()
            }
            val rejected=root.optJSONObject("rejectedZones")?.keys()?.asSequence()?.toSet() ?: emptySet()
            require(rejected.size<=1000 && rejected.none {it in names})
            return ProviderZoneDatabase(models,names,rejected)
        }
        internal fun parseTail(text: String): ProviderZone.Tail {
            val token="(?:<[A-Za-z0-9+\\-]{3,}>|[A-Za-z]{3,})";val number="[+-]?\\d{1,3}(?::\\d{1,2}(?::\\d{1,2})?)?"
            val match=Regex("^($token)($number)($token)?($number)?(?:,([^,]+),([^,]+))?$").matchEntire(text) ?: error("invalid-timezone-future")
            fun seconds(value: String,limit: Int): Int {
                require(value.matches(Regex(number)))
                val parts=value.trimStart('+','-').split(':').map {it.toInt()};require(parts[0]<=limit && parts.drop(1).all {it<=59})
                return (if(value.startsWith('-')) -1 else 1)*(parts[0]*3600+(parts.getOrNull(1) ?: 0)*60+(parts.getOrNull(2) ?: 0))
            }
            fun name(value: String)=value.removePrefix("<").removeSuffix(">")
            fun rule(value: String): ProviderZone.DateRule {
                val pieces=value.split('/');require(pieces.size<=2)
                val date=pieces[0];val clock=if(pieces.size==2) seconds(pieces[1],167) else 7200
                val month=Regex("M(\\d{1,2})\\.([1-5])\\.([0-6])").matchEntire(date)
                return if(month!=null) {
                    val a=month.groupValues[1].toInt();require(a in 1..12)
                    ProviderZone.DateRule("M",a,month.groupValues[2].toInt(),month.groupValues[3].toInt(),clock)
                } else if(date.matches(Regex("J\\d{1,3}"))) {
                    val a=date.drop(1).toInt();require(a in 1..365);ProviderZone.DateRule("J",a,0,0,clock)
                } else {require(date.matches(Regex("\\d{1,3}")));val a=date.toInt();require(a in 0..365);ProviderZone.DateRule("N",a,0,0,clock)}
            }
            val standard=-seconds(match.groupValues[2],24)
            val dst=match.groups[3]?.value
            if(dst==null) {
                require(match.groups[4]==null && match.groups[5]==null && match.groups[6]==null)
                return ProviderZone.Tail(standard,name(match.groupValues[1]),null,null,null,null,text)
            }
            require(match.groups[5]!=null && match.groups[6]!=null)
            val daylight=match.groups[4]?.value?.let {-seconds(it,24)} ?: standard+3600
            require(standard in -89999..93599 && daylight in -89999..93599)
            return ProviderZone.Tail(standard,name(match.groupValues[1]),daylight,name(dst),rule(match.groupValues[5]),rule(match.groupValues[6]),text)
        }
    }
}
