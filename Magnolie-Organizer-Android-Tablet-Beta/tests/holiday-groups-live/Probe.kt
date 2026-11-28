package io.gitlab.maik3531.magnolietabletbeta
import org.json.JSONObject
import org.json.JSONArray
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path

fun row(codes: List<String> = emptyList(), nationwide:Boolean=false, subdivisions:List<String> = emptyList(), name:String="Break", start:String="2026-12-20",end:String="2027-01-04", rawGroups:Any?=null):JSONObject = JSONObject(mapOf("startDate" to start,"endDate" to end,"name" to name,"nationwide" to nationwide,"groups" to (rawGroups ?: JSONArray(codes.map{JSONObject(mapOf("code" to it))})),"subdivisions" to JSONArray(subdivisions.map{JSONObject(mapOf("code" to it))})))
fun run(country:String, regions:List<String>, school:Boolean=true, years:List<Int> = listOf(2026), rows:(String,Map<String,String>)->List<JSONObject>):Pair<HolidayService.Result,List<Pair<String,Map<String,String>>>> {
    val requests=mutableListOf<Pair<String,Map<String,String>>>()
    val service=HolidayService(BoundedHttpTransport { request, _ ->
        val endpoint=request.uri.path.substringAfterLast('/')
        val fields=request.uri.rawQuery.split('&').associate { val p=it.split('=',limit=2); URLDecoder.decode(p[0],StandardCharsets.UTF_8) to URLDecoder.decode(p[1],StandardCharsets.UTF_8) }
        requests.add(endpoint to fields)
        Response(200,JSONArray(rows(endpoint,fields)).toString().encodeToByteArray())
    })
    return service.fetch(HolidayService.Query(country,regions.map{HolidayService.Region(it,it)},years,school)) to requests
}
fun main(args: Array<String>) {
    var passed=0; var total=0
    fun checkCase(name:String, action:()->Boolean){total++;try{if(action()){passed++;println("PASS $name")}else println("FAIL $name")}catch(e:Exception){println("FAIL $name: ${e.message}")}}
    val byCountry=mapOf("BE" to listOf("BE-DE","BE-FR","BE-NL"),"NL" to listOf("NL-NO","NL-MI","NL-ZU"))
    for((country,codes) in byCountry) {
        for(code in codes) {
            val (result,reqs)=run(country,listOf(code)){endpoint,_-> if(endpoint=="PublicHolidays")listOf(row(nationwide=true))else listOf(row(listOf(code)))}
            checkCase("$code group URL"){reqs.any{it.first=="SchoolHolidays" && it.second["groupCode"]==code && "subdivisionCode" !in it.second}}
            checkCase("$code national public URL"){reqs.count{it.first=="PublicHolidays" && "subdivisionCode" !in it.second && "groupCode" !in it.second}==1}
            checkCase("$code group coverage"){result.coverage.any{it.kind=="school-holiday" && it.region==code}}
            checkCase("$code cross-year inclusive interval"){result.entries.any{it.kind=="school-holiday"&&it.start=="2026-12-20"&&it.end=="2027-01-04"&&it.regions==listOf(code)}}
        }
        val (multi,multiReq)=run(country,codes){endpoint,_->if(endpoint=="PublicHolidays")listOf(row(nationwide=true))else listOf(row(codes))}
        checkCase("$country one public request"){multiReq.count{it.first=="PublicHolidays"}==1}
        checkCase("$country union and label"){multi.entries.single{it.kind=="school-holiday"}.let{it.regions.toSet()==codes.toSet() && it.regionLabel==codes.sorted().joinToString(", ")}}
        val (national,_)=run(country,emptyList()){endpoint,_->if(endpoint=="PublicHolidays")listOf(row(nationwide=true))else codes.map{row(listOf(it))}}
        checkCase("$country all group coverage"){national.coverage.any{it.kind=="school-holiday"&&it.region==""} && national.entries.single{it.kind=="school-holiday"}.regions.toSet()==codes.toSet()}
        for((label,fixture) in listOf("missing" to listOf(row()),"foreign" to listOf(row(listOf("XX-1"))),"wrong" to listOf(row(listOf(codes[1]))),"explicit local" to listOf(row(codes,subdivisions=listOf("$country-X")).put("regionalScope","Local")),"malformed" to listOf(row(rawGroups="bad")),"empty" to emptyList())) {
            val (r,_)=run(country,listOf(codes[0])){endpoint,_->if(endpoint=="PublicHolidays")listOf(row(nationwide=true))else fixture}
            checkCase("$country $label no school coverage"){r.coverage.none{it.kind=="school-holiday"}}
            checkCase("$country $label no invented school entry"){r.entries.none{it.kind=="school-holiday"}}
        }
        val (partial,_)=run(country,emptyList()){endpoint,_->if(endpoint=="PublicHolidays")listOf(row(nationwide=true))else listOf(row(listOf(codes[0])))}
        checkCase("$country partial national no coverage"){partial.coverage.none{it.kind=="school-holiday"} && partial.entries.any{it.kind=="school-holiday"&&it.regions==listOf(codes[0])}}
        val (optOut,optReq)=run(country,codes,false){_,_->listOf(row(nationwide=true))}
        checkCase("$country opt-out single public"){optReq.size==1 && optOut.coverage.single().region==""}
        checkCase("$country mixed query rejected"){try{run(country,listOf(codes[0],"$country-X")){_,_->emptyList()};false}catch(e:HolidayException){e.code=="holiday_invalid_query"}}
    }
    for((country,region,provider) in listOf(Triple("AT","AT-9","AT-WI"),Triple("DE","DE-BY","DE-BY"))) {
        val(r,reqs)=run(country,listOf(region)){_,_->listOf(row(subdivisions=listOf(provider)))}
        checkCase("$country existing subdivision URL"){reqs.size==2&&reqs.all{it.second["subdivisionCode"]==provider&&"groupCode" !in it.second}}
        checkCase("$country existing coverage and ISO"){r.coverage.size==2&&r.entries.all{it.regions==listOf(region)}}
    }
    val (polish, polishRequests) = run("PL", emptyList(), years = listOf(2026, 2027, 2028)) { _, _ -> emptyList() }
    checkCase("Poland holds only the known bad school years") {
        polishRequests.filter { it.first == "SchoolHolidays" }.map { it.second["validFrom"] } == listOf("2028-01-01") &&
            polish.coverage.filter { it.kind == "school-holiday" }.map { it.start } == listOf("2028-01-01") &&
            polish.coverage.filter { it.kind == "public-holiday" }.map { it.start } == listOf("2026-01-01", "2027-01-01", "2028-01-01")
    }
    // Refs #857: exact bytes captured from the country and group endpoints.
    val fixtures = Path.of(args.single())
    for ((country,codes) in byCountry) for (selected in listOf("") + codes) {
        val requests = mutableListOf<Pair<String,Map<String,String>>>()
        val service=HolidayService(BoundedHttpTransport { request,_ ->
            val endpoint=request.uri.path.substringAfterLast('/')
            val fields=request.uri.rawQuery.split('&').associate { val p=it.split('=',limit=2); URLDecoder.decode(p[0],StandardCharsets.UTF_8) to URLDecoder.decode(p[1],StandardCharsets.UTF_8) }
            requests.add(endpoint to fields)
            val prefix=if(endpoint=="SchoolHolidays") fields["groupCode"] ?: country else country
            Response(200,Files.readAllBytes(fixtures.resolve("$prefix-$endpoint.json")))
        })
        val result=service.fetch(HolidayService.Query(country,if(selected.isEmpty())emptyList() else listOf(HolidayService.Region(selected,selected)),listOf(2026),true))
        val raw=JSONArray(Files.readString(fixtures.resolve("${selected.ifEmpty{country}}-SchoolHolidays.json")))
        val expected=mutableMapOf<Triple<String,String,String>,MutableSet<String>>()
        for (i in 0 until raw.length()) {
            val item=raw.getJSONObject(i)
            val key=Triple(item.getString("startDate"),item.getString("endDate"),item.getJSONArray("name").getJSONObject(0).getString("text"))
            val groupIds=item.getJSONArray("groups")
            val identities=expected.getOrPut(key){sortedSetOf()}
            for(j in 0 until groupIds.length()) identities.add(groupIds.getJSONObject(j).getString("code"))
        }
        checkCase("${selected.ifEmpty{country}} captured groups and dates exact") {
            result.entries.filter{it.kind=="school-holiday"}.associate{Triple(it.start,it.end,it.name) to it.regions.toSet()}==expected
        }
        checkCase("${selected.ifEmpty{country}} captured group coverage") {result.coverage.filter{it.kind=="school-holiday"}.map{it.region}==listOf(selected)}
        checkCase("${selected.ifEmpty{country}} captured public scope") {result.coverage.any{it.kind=="public-holiday"&&it.region==""} && requests.filter{it.first=="PublicHolidays"}.all{"groupCode" !in it.second && "subdivisionCode" !in it.second}}
    }
    for((country,codes) in byCountry) {
        val code=codes[0]
        fun one(fixture:JSONObject, selected:Boolean=true): HolidayService.Result = run(country,if(selected)listOf(code) else emptyList()){endpoint,_->if(endpoint=="PublicHolidays")listOf(row(nationwide=true))else listOf(fixture)}.first
        val expanded=row(listOf(code),subdivisions=listOf("$country-MUNICIPAL"))
        val result=one(expanded)
        checkCase("$country expanded groups keep only group identity") {result.entries.single{it.kind=="school-holiday"}.regions==listOf(code) && result.coverage.any{it.kind=="school-holiday"&&it.region==code}}
        val exception=one(row(listOf(code),subdivisions=listOf("$country-MUNICIPAL")).put("tags",JSONArray(listOf("Exception"))))
        checkCase("$country Exception tag alone preserves group") {exception.entries.single{it.kind=="school-holiday"}.regions==listOf(code) && exception.coverage.any{it.kind=="school-holiday"}}
        val national=one(row(codes,nationwide=true,subdivisions=listOf("$country-MUNICIPAL")))
        checkCase("$country all groups nationwide expansion consistent") {national.entries.single{it.kind=="school-holiday"}.regions.toSet()==codes.toSet() && national.coverage.any{it.kind=="school-holiday"}}
        val local=one(row(listOf(code),subdivisions=listOf("$country-MUNICIPAL")).put("regionalScope","Local"),false)
        checkCase("$country explicit Local country retained locally") {local.entries.single{it.kind=="school-holiday"}.regions==listOf("$country-MUNICIPAL") && local.coverage.none{it.kind=="school-holiday"}}
        val subdivisionOnly=one(row(subdivisions=listOf("$country-MUNICIPAL")),false)
        checkCase("$country subdivision-only country retained locally") {subdivisionOnly.entries.single{it.kind=="school-holiday"}.regions==listOf("$country-MUNICIPAL") && subdivisionOnly.coverage.none{it.kind=="school-holiday"}}
        for (invalid in listOf("Unknown",42,JSONObject.NULL)) {
            val r=one(row(listOf(code)).put("regionalScope",invalid))
            checkCase("$country invalid regionalScope $invalid grants no coverage") {r.entries.single{it.kind=="school-holiday"}.regions==listOf(code) && r.coverage.none{it.kind=="school-holiday"}}
        }
        for((label,bad) in listOf("foreign subdivision" to row(listOf(code),subdivisions=listOf("XX-FOREIGN")),"prefixless subdivision" to row(listOf(code),subdivisions=listOf("MUNICIPAL")),"malformed subdivisions" to row(listOf(code)).put("subdivisions","invalid"),"local without local identity" to row(listOf(code)).put("regionalScope","Local"))) {
            checkCase("$country $label rejected") {
                try {val r=one(bad);r.entries.none{it.kind=="school-holiday"} && r.coverage.none{it.kind=="school-holiday"}} catch(e:HolidayException){e.code=="holiday_invalid_response"}
            }
        }
    }
    println("$passed/$total"); if(passed!=total) kotlin.system.exitProcess(1)
}
