package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject

internal fun eligibleAlarms(value: JSONObject, now: Long): List<JSONObject> {
    if (!value.optBoolean("enabled")) return emptyList()
    val alarms = value.optJSONArray("alarms") ?: JSONArray()
    val delivered = value.optJSONObject("delivered") ?: JSONObject()
    return (0 until alarms.length()).map { alarms.getJSONObject(it) }.filter {
        (!it.getBoolean("custom") || value.optBoolean("customEnabled")) &&
            !delivered.has(it.getString("id")) && it.getLong("at") >= now - 24 * 60 * 60 * 1000
    }.sortedBy { it.getLong("at") }
}
