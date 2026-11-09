package io.gitlab.maik3531.magnolietabletbeta

import java.io.File
import org.json.JSONArray
import org.json.JSONObject

/** Offline AOSP JSON differential. No Android runtime or acceptance claim. */
fun main(args:Array<String>) {
    require(args.size==2)
    val smoke=File(args[1]).readText()
    val ignored=Regex("private val ignored = setOf\\(([^\\n]+)\\)").find(smoke)!!.groupValues[1]
        .let {Regex("\"([^\"]+)\"").findAll(it).map {m->m.groupValues[1]}.toSet()}
    fun semantic(v:Any?):Any?=when(v) {
        null,JSONObject.NULL->null
        is JSONObject->v.keys().asSequence().toList().sorted().associateWith {semantic(v.get(it))}
        is JSONArray->(0 until v.length()).map {semantic(v.get(it))}
        is Number->v.toDouble()
        else->v
    }
    fun stable(v:JSONObject)=semantic(JSONObject(v.toString()).also {c->ignored.forEach {c.remove(it)}}) as Map<*,*>
    var differences=0
    fun compare(expected:JSONArray,observed:JSONArray,label:String) {
        check(expected.length()==observed.length())
        for(record in 0 until expected.length()) {
            val left=stable(expected.getJSONObject(record));val right=stable(observed.getJSONObject(record))
            if(left!=right) {
                differences++
                val fields=JSONObject()
                (left.keys+right.keys).map {it.toString()}.toSet().sorted().filter {left[it]!=right[it]}.forEach {key ->
                    fields.put(key,JSONObject().put("expected",left[key] ?: JSONObject.NULL).put("actual",right[key] ?: JSONObject.NULL))
                }
                println(JSONObject().put("case",label).put("record",record).put("differences",fields))
            }
        }
    }
    val cases=JSONObject(File(args[0]).readText()).getJSONArray("cases")
    val groups=mapOf("ics-termine" to "termine","ics-aufgaben" to "aufgaben","ics-jahrestage" to "jahrestage")
    for(i in 0 until cases.length()) {
        val case=cases.getJSONObject(i);val name=case.getString("name")
        val actual=ICalendarImport.decode(case.getString("importSource").toByteArray(Charsets.UTF_8),"UTC").document
        for((kind,group) in groups) {
            val expected=case.getJSONObject("importExpected").getJSONArray(group);val observed=actual.getJSONArray(group)
            compare(expected,observed,"$name/import/$group")
            if(observed.length()>0) {
                val export=ICalendarExport.encode((0 until observed.length()).map {observed.getJSONObject(it)},kind,"UTC")
                compare(expected,ICalendarImport.decode(export.toByteArray(),"UTC").document.getJSONArray(group),"$name/reexport/$group")
            }
        }
        val records=case.getJSONArray("records");val kind=case.getString("kind")
        val export=ICalendarExport.encode((0 until records.length()).map {records.getJSONObject(it)},kind,"UTC")
        compare(case.getJSONArray("expected"),ICalendarImport.decode(export.toByteArray(),"UTC").document.getJSONArray(groups.getValue(kind)),"$name/export")
    }
    println(JSONObject().put("semanticRecordDifferences",differences))
    check(differences==0) {"Native-compatible JSON semantic mismatch"}
}
