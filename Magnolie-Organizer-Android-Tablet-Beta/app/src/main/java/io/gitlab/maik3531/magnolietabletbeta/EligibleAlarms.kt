package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject

internal fun alarmDeliveryKey(alarm: JSONObject): String =
    if (alarm.has("deliveryKey")) alarm.getString("deliveryKey") else alarm.getString("id")

private val legacyMode = Regex(":(absolute|early-[1-7])$")

private fun alarmKeys(alarms: List<JSONObject>, book: JSONObject?): List<String> {
    if (alarms.all { it.has("deliveryKey") }) return alarms.map(::alarmDeliveryKey)
    val sources = mutableMapOf<String, MutableList<String>>()
    for ((section, collection) in listOf("kalender" to "termine", "aufgaben" to "aufgaben")) {
        val entries = book?.optJSONArray(collection) ?: continue
        for (index in 0 until entries.length()) {
            val item = entries.optJSONObject(index) ?: continue
            val id = item.optString("id")
            if (id.isEmpty()) continue
            val source = item.optString("icsQuelleId").ifEmpty { item.optString("syncKalenderUid") }
                .ifEmpty { item.optJSONObject("kalenderQuelle")?.optString("id").orEmpty() }
            sources.getOrPut("$section:$id") { mutableListOf() }.add(source)
        }
    }
    return alarms.map { alarm ->
        if (alarm.has("deliveryKey")) return@map alarmDeliveryKey(alarm)
        val legacyId = alarm.getString("id")
        val section = alarm.getString("section")
        val at = alarm.getLong("at")
        val suffix = ":$at"
        if (!legacyId.startsWith("$section:") || !legacyId.endsWith(suffix)) return@map legacyId
        val withMode = legacyId.removeSuffix(suffix)
        val withoutMode = withMode.replace(legacyMode, "")
        // An older row did not qualify the source. Resolve its local ID against
        // the book that produced it; don't infer equivalence across ambiguous IDs.
        val base = listOf(withMode, withoutMode).distinct().filter(sources::containsKey).singleOrNull()
        val custom = alarm.getBoolean("custom") && withoutMode.startsWith("$section:custom:")
        val cycle = section == "kalender" && (withoutMode.startsWith("kalender:cycle-estimate:") ||
            withoutMode.startsWith("kalender:cycle-deviation:"))
        val source = if (base == null) {
            if (sources.containsKey(withMode) || sources.containsKey(withoutMode) || !custom && !cycle) return@map legacyId
            ""
        } else {
            sources.getValue(base).singleOrNull() ?: return@map legacyId
        }
        val id = (base ?: withoutMode).removePrefix("$section:")
        val parts = JSONArray().put(section).put(source).put(id).put(at)
        // Match the WebView's JSON.stringify escaping for the durable key.
        VaultJson.encode(JSONObject().put("key", parts), MAX_BYTES)
            .removePrefix("{\"key\":").removeSuffix("}").replace("\\/", "/")
    }
}

private fun receipts(alarms: List<JSONObject>, keys: List<String>, delivered: JSONObject): JSONObject {
    val grouped = JSONObject()
    for ((index, alarm) in alarms.withIndex()) {
        val key = keys[index]
        val id = alarm.getString("id")
        when {
            delivered.has(key) -> grouped.put(key, delivered.get(key))
            !alarm.has("deliveryKey") && delivered.has(id) -> grouped.put(key, delivered.get(id))
        }
    }
    return grouped
}

internal fun retainAlarmReceipts(
    previous: JSONArray, previousBook: JSONObject?, active: JSONArray, delivered: JSONObject
): JSONObject {
    if (delivered.length() == 0) return JSONObject()
    val oldAlarms = (0 until previous.length()).map(previous::getJSONObject)
    val oldReceipts = receipts(oldAlarms, alarmKeys(oldAlarms, previousBook), delivered)
    val retained = JSONObject()
    for (index in 0 until active.length()) {
        val key = alarmDeliveryKey(active.getJSONObject(index))
        if (oldReceipts.has(key)) retained.put(key, oldReceipts.get(key))
    }
    return retained
}

internal fun eligibleAlarms(value: JSONObject, now: Long): List<JSONObject> {
    if (!value.optBoolean("enabled")) return emptyList()
    val rows = value.optJSONArray("alarms") ?: JSONArray()
    val alarms = (0 until rows.length()).map(rows::getJSONObject)
    val keys = alarmKeys(alarms, value.optJSONObject("data"))
    val delivered = receipts(alarms, keys, value.optJSONObject("delivered") ?: JSONObject())
    val customEnabled = value.optBoolean("customEnabled")
    val selected = mutableSetOf<String>()
    return alarms.mapIndexedNotNull { index, alarm ->
        val key = keys[index]
        if (alarm.getBoolean("custom") && !customEnabled || delivered.has(key) ||
            alarm.getLong("at") < now - 24 * 60 * 60 * 1000 || !selected.add(key)) return@mapIndexedNotNull null
        if (key == alarmDeliveryKey(alarm)) alarm else JSONObject(alarm.toString()).put("deliveryKey", key)
    }.sortedBy { it.getLong("at") }
}
