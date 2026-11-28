package io.gitlab.maik3531.magnolietabletbeta
import org.json.JSONObject
import org.json.JSONArray
import java.net.URLDecoder
import java.nio.charset.StandardCharsets

fun row(codes: List<String> = emptyList(), nationwide:Boolean=false, subdivisions:List<String> = emptyList(), name:String="Break", start:String="2026-12-20",end:String="2027-01-04", rawGroups:Any?=null):JSONObject = JSONObject(mapOf("startDate" to start,"endDate" to end,"name" to name,"nationwide" to nationwide,"groups" to (rawGroups ?: JSONArray(codes.map{JSONObject(mapOf("code" to it))})),"subdivisions" to JSONArray(subdivisions.map{JSONObject(mapOf("code" to it))})))
fun run(country:String, regions:List<String>, school:Boolean=true, rows:(String,Map<String,String>)->List<JSONObject>):Pair<HolidayService.Result,List<Pair<String,Map<String,String>>>> {
    val requests=mutableListOf<Pair<String,Map<String,String>>>()
    val service=HolidayService(BoundedHttpTransport { request, _ ->
        val endpoint=request.uri.path.substringAfterLast('/')
        val fields=request.uri.rawQuery.split('&').associate { val p=it.split('=',limit=2); URLDecoder.decode(p[0],StandardCharsets.UTF_8) to URLDecoder.decode(p[1],StandardCharsets.UTF_8) }
        requests.add(endpoint to fields)
        val id="${requests.size}"
        Fixtures.responses[id]=JSONArray(rows(endpoint,fields))
        Response(200,id.encodeToByteArray())
    })
    return service.fetch(HolidayService.Query(country,regions.map{HolidayService.Region(it,it)},listOf(2026),school)) to requests
}
fun main() {
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
        for((label,fixture) in listOf("missing" to listOf(row()),"foreign" to listOf(row(listOf("XX-1"))),"wrong" to listOf(row(listOf(codes[1]))),"mixed" to listOf(row(codes,subdivisions=listOf("$country-X"))),"malformed" to listOf(row(rawGroups="bad")),"empty" to emptyList())) {
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
    println("$passed/$total"); if(passed!=total) kotlin.system.exitProcess(1)
}
