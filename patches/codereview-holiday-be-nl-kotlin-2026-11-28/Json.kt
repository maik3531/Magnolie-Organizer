package org.json
class JSONObject(private val fields: Map<String, Any?>) {
    fun opt(key: String): Any? = fields[key]
    fun has(key: String) = fields.containsKey(key)
    companion object { val NULL = Any() }
}
class JSONArray(private val values: List<Any?>) {
    fun length() = values.size
    fun opt(i: Int): Any? = values.getOrNull(i)
}
