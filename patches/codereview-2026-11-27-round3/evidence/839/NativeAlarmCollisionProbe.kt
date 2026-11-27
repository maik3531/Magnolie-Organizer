package io.gitlab.maik3531.magnolietabletbeta

import java.io.File
import org.json.JSONArray
import org.json.JSONObject

fun main(args: Array<String>) {
    val records=JSONArray(File(args[0]).readText())
    val alarms=records.getJSONObject(1).getJSONArray("savedAlarms")
    val now=1904639400000L
    val state=JSONObject().put("enabled",true).put("customEnabled",false)
        .put("alarms",alarms).put("delivered",JSONObject())
    state.put("data",JSONObject().put("termine",JSONArray().put(
        JSONObject(File(args[1]).readText()).put("id","coincident-event"))).put("aufgaben",JSONArray()))
    val eligible=eligibleAlarms(state,now)
    val report=JSONObject().put("expectedInitial",1).put("actualInitial",eligible.size)
    state.getJSONObject("delivered").put(alarms.getJSONObject(0).getString("id"),now)
    report.put("expectedAfterAbsoluteReceipt",0).put("actualAfterAbsoluteReceipt",eligibleAlarms(state,now).size)
    println(report.toString(2))
    check(eligible.size==1 && eligibleAlarms(state,now).isEmpty())
}
